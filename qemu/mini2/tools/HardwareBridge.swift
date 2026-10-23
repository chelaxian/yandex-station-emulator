import AppKit
import CoreBluetooth
import AVFoundation
import Network

final class Bridge: NSObject, CBPeripheralManagerDelegate {
    var peripheral: CBPeripheralManager!
    var chars: [CBMutableCharacteristic] = []
    var subscribed = false
    var lastStatus = Data()
    var engine: AVAudioEngine?
    var listener: NWListener?
    var micClients: [NWConnection] = []
    var pending: [ObjectIdentifier:Int] = [:]
    var state: [String: Any] = ["bluetooth":"starting","microphone":"starting"]
    let root: String
    init(root: String) { self.root=root; super.init() }
    func save() {
        state["timestamp"] = Date().timeIntervalSince1970
        if let d=try? JSONSerialization.data(withJSONObject:state,options:.sortedKeys) {
            try? d.write(to:URL(fileURLWithPath:root+"/run/hardware.json"),options:.atomic)
        }
    }
    func start() {
        peripheral=CBPeripheralManager(delegate:self,queue:.main)
        AVCaptureDevice.requestAccess(for:.audio) { allowed in DispatchQueue.main.async {
            if allowed { self.startMic() } else { self.state["microphone"]="permission_denied";self.save() }
        }}
        Timer.scheduledTimer(withTimeInterval:1,repeats:true) { _ in
            guard self.subscribed else { return }
            self.rpc("read",3) { data in
                guard let data=data, data != self.lastStatus else { return }
                if self.peripheral.updateValue(data,for:self.chars[3],onSubscribedCentrals:nil) {self.lastStatus=data}
            }
        }
    }
    func rpc(_ action:String,_ index:Int,_ data:Data=Data(),_ offset:Int=0,done:@escaping(Data?)->Void) {
        var req=URLRequest(url:URL(string:"http://127.0.0.1:19092/")!)
        req.httpMethod="POST";req.timeoutInterval=12;req.setValue("application/json",forHTTPHeaderField:"Content-Type")
        req.httpBody=try? JSONSerialization.data(withJSONObject:["action":action,"index":index,"data":data.base64EncodedString(),"offset":offset])
        URLSession.shared.dataTask(with:req) { bytes,_,_ in
            let json=bytes.flatMap {try? JSONSerialization.jsonObject(with:$0) as? [String:Any]}
            let result=(json?["ok"] as? Bool == true) ? (json?["data"] as? String).flatMap{Data(base64Encoded:$0)} : nil
            DispatchQueue.main.async {done(result)}
        }.resume()
    }
    func peripheralManagerDidUpdateState(_ p:CBPeripheralManager) {
        state["bluetooth"]=String(describing:p.state.rawValue);save()
        guard p.state == .poweredOn else {return}
        let ids=["f25d4a0d-6266-4254-943e-3e20606f2fa6","4276d829-46ce-4ce9-9f30-30dbb9a43724","29d49103-16f4-4fcd-85c7-42d0e43d16d9","9879f69f-510f-4a0c-b500-79de90342997","5b66e7df-1b0f-4a9d-8492-5c3f3b866c80","e985aa00-e701-4d5d-96b9-f38ae3d7ee16"]
        let properties:[CBCharacteristicProperties]=[.write,.read,.write,[.read,.notify],.write,.read]
        chars=ids.enumerated().map { i,id in CBMutableCharacteristic(type:CBUUID(string:id),properties:properties[i],value:nil,permissions:properties[i].contains(.write) ? .writeable : .readable) }
        let service=CBMutableService(type:CBUUID(string:"664578b6-c390-42d8-956e-c1ae8b646436"),primary:true)
        service.characteristics=chars;p.add(service)
    }
    func peripheralManager(_ p:CBPeripheralManager,didAdd service:CBService,error:Error?) {
        if let error=error {state["bluetooth"]=error.localizedDescription;save();return}
        p.startAdvertising([CBAdvertisementDataLocalNameKey:"Yandex Station Mini 2 NK8K",CBAdvertisementDataServiceUUIDsKey:[service.uuid]])
    }
    func peripheralManagerDidStartAdvertising(_ p:CBPeripheralManager,error:Error?) {
        state["bluetooth"]=error?.localizedDescription ?? "advertising";state["advertising"]=p.isAdvertising;save()
    }
    func peripheralManager(_ p:CBPeripheralManager,didReceiveRead request:CBATTRequest) {
        guard let i=chars.firstIndex(where:{$0.uuid==request.characteristic.uuid}) else {p.respond(to:request,withResult:.attributeNotFound);return}
        rpc("read",i,Data(),0) { data in
            guard let data=data else {p.respond(to:request,withResult:.unlikelyError);return}
            guard request.offset<=data.count else {p.respond(to:request,withResult:.invalidOffset);return}
            request.value=Data(data.dropFirst(request.offset));p.respond(to:request,withResult:.success)
        }
    }
    func peripheralManager(_ p:CBPeripheralManager,didReceiveWrite requests:[CBATTRequest]) {
        guard let first=requests.first,let i=chars.firstIndex(where:{$0.uuid==first.characteristic.uuid}),requests.allSatisfy({$0.characteristic.uuid==first.characteristic.uuid}) else {return}
        var data=Data();for r in requests.sorted(by:{$0.offset<$1.offset}) {data.append(r.value ?? Data())}
        rpc("write",i,data,first.offset) { result in p.respond(to:first,withResult:result == nil ? .unlikelyError : .success) }
    }
    func peripheralManager(_ p:CBPeripheralManager,central:CBCentral,didSubscribeTo characteristic:CBCharacteristic) {subscribed=true;state["phone_connected"]=true;save();rpc("subscribe",3){_ in}}
    func peripheralManager(_ p:CBPeripheralManager,central:CBCentral,didUnsubscribeFrom characteristic:CBCharacteristic) {subscribed=false;state["phone_connected"]=false;save();rpc("unsubscribe",3){_ in}}
    func startMic() {
        do {
            let params=NWParameters.tcp;params.requiredLocalEndpoint = .hostPort(host:"127.0.0.1",port:19093)
            listener=try NWListener(using:params)
            listener?.newConnectionHandler = { conn in
                DispatchQueue.main.async {self.micClients.append(conn);conn.stateUpdateHandler={ s in if case .failed = s {DispatchQueue.main.async {self.micClients.removeAll{$0 === conn}}}};conn.start(queue:.main)}
            };listener?.start(queue:.main)
            let eng=AVAudioEngine();let input=eng.inputNode;let format=input.outputFormat(forBus:0)
            guard format.sampleRate>0,let out=AVAudioFormat(commonFormat:.pcmFormatInt16,sampleRate:48000,channels:2,interleaved:true),let converter=AVAudioConverter(from:format,to:out) else {throw NSError(domain:"MicFormat",code:1)}
            input.installTap(onBus:0,bufferSize:1024,format:format) { buffer,_ in
                let capacity=AVAudioFrameCount(Double(buffer.frameLength)*48000/format.sampleRate)+64
                guard let pcm=AVAudioPCMBuffer(pcmFormat:out,frameCapacity:capacity) else {return}
                var supplied=false;var error:NSError?
                converter.convert(to:pcm,error:&error) { _,status in if supplied {status.pointee = .noDataNow;return nil};supplied=true;status.pointee = .haveData;return buffer }
                guard pcm.frameLength>0,let pointer=pcm.int16ChannelData?[0] else {return}
                let data=Data(bytes:pointer,count:Int(pcm.frameLength)*4)
                var energy:Double=0;for i in 0..<Int(pcm.frameLength)*2 {let v=Double(pointer[i])/32768;energy+=v*v}
                let rms=sqrt(energy/Double(pcm.frameLength*2))
                DispatchQueue.main.async {self.state["microphone"]="capturing";self.state["mic_rms"]=rms;self.state["mic_clients"]=self.micClients.count;self.save();for c in self.micClients {
                    let id=ObjectIdentifier(c)
                    if self.pending[id,default:0]>=4 {continue}
                    self.pending[id,default:0]+=1
                    c.send(content:data,completion:.contentProcessed{_ in DispatchQueue.main.async {self.pending[id,default:1]-=1}})
                }}
            }
            try eng.start();engine=eng;state["microphone"]="capturing";save()
        } catch {state["microphone"]=error.localizedDescription;save()}
    }
}
let app=NSApplication.shared
app.setActivationPolicy(.accessory)
let bridge=Bridge(root:CommandLine.arguments.dropFirst().first ?? FileManager.default.currentDirectoryPath)
bridge.start()
app.run()
