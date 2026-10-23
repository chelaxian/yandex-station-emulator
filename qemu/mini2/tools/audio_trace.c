extern void *dlsym(void*,const char*);
extern int open(const char*,int,...),close(int),snprintf(char*,unsigned,const char*,...),write(int,const void*,unsigned);
static void log_open(const char *name,int stream,int result){char b[240];int n=snprintf(b,sizeof(b),"snd_pcm_open name=%s stream=%d result=%d\n",name,stream,result);int f=open("/tmp/audio-calls.log",1089,0600);if(f>=0){write(f,b,n);close(f);}}
int snd_pcm_open(void **pcm,const char *name,int stream,int mode){
 int (*next)(void**,const char*,int,int)=dlsym((void*)-1,"snd_pcm_open");
 log_open(name,stream,999);int result=next(pcm,name,stream,mode);log_open(name,stream,result);return result;
}
__attribute__((constructor)) static void loaded(void){log_open("trace-loaded",-1,0);}
