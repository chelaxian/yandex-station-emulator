/* Local probe adapter for the supplied Quasar PEM pair. No key generation. */
typedef unsigned int size_t;
typedef struct bio_st BIO;
typedef struct evp_pkey_st EVP_PKEY;
typedef struct evp_md_ctx_st EVP_MD_CTX;
extern int socket(int,int,int),bind(int,const void*,unsigned),listen(int,int),accept(int,void*,void*),close(int),unlink(const char*);
extern int read(int,void*,unsigned),write(int,const void*,unsigned),puts(const char*),printf(const char*,...);
extern void *memcpy(void*,const void*,unsigned),*memset(void*,int,unsigned);
extern unsigned strlen(const char*);
extern BIO *BIO_new_file(const char*,const char*);
extern int BIO_free(BIO*);
extern EVP_PKEY *PEM_read_bio_PrivateKey(BIO*,EVP_PKEY**,void*,void*);
extern EVP_MD_CTX *EVP_MD_CTX_new(void);
extern void EVP_MD_CTX_free(EVP_MD_CTX*);
extern const void *EVP_sha256(void);
extern int EVP_DigestSignInit(EVP_MD_CTX*,void*,const void*,void*,EVP_PKEY*);
extern int EVP_DigestSign(EVP_MD_CTX*,unsigned char*,size_t*,const unsigned char*,size_t);
extern void *EVP_PKEY_get1_RSA(EVP_PKEY*);
extern int RSA_private_decrypt(int,const unsigned char*,unsigned char*,void*,int);
extern void RSA_free(void*);
extern void *fopen(const char*,const char*);
extern unsigned fread(void*,unsigned,unsigned,void*);
extern int fclose(void*);
extern int fflush(void*);
static unsigned char request[65536],nested[65536],response[65536],result[8192],public_pem[4096];
static int exact(int fd,void *p,unsigned n,int out) { unsigned k=0; while(k<n){int r=out?write(fd,(char*)p+k,n-k):read(fd,(char*)p+k,n-k);if(r<=0)return 0;k+=r;}return 1; }
static unsigned varint(unsigned char *p,unsigned v){unsigned n=0;do{p[n]=(v&127)|(v>127?128:0);v>>=7;n++;}while(v);return n;}
static unsigned getvar(const unsigned char *p,unsigned n,unsigned *offset){unsigned v=0,s=0;while(*offset<n&&s<32){unsigned c=p[(*offset)++];v|=(c&127)<<s;if(!(c&128))return v;s+=7;}return 0;}
static unsigned bytes(unsigned char *p,unsigned field,const unsigned char *data,unsigned n){unsigned k=varint(p,field*8+2);k+=varint(p+k,n);memcpy(p+k,data,n);return k+n;}
int main(int argc,char **argv,char **env){
 (void)env;if(argc!=4){puts("usage: pem_proxy private.pem public.pem socket");return 2;}
 BIO *bio=BIO_new_file(argv[1],"r");if(!bio)return 3;
 EVP_PKEY *key=PEM_read_bio_PrivateKey(bio,0,0,0);BIO_free(bio);if(!key)return 4;
 void *f=fopen(argv[2],"rb");if(!f)return 5;unsigned public_size=fread(public_pem,1,sizeof(public_pem),f);fclose(f);
 struct {unsigned short family;char path[108];} addr;memset(&addr,0,sizeof(addr));addr.family=1;
 if(strlen(argv[3])>=108)return 6;memcpy(addr.path,argv[3],strlen(argv[3]));unlink(argv[3]);
 int server=socket(1,1,0);if(server<0||bind(server,&addr,sizeof(addr))||listen(server,8))return 7;
 puts("PEM adapter listening (local experiment)");
 fflush(0);
 for(;;){int fd=accept(server,0,0);if(fd<0)continue;
  for(;;){unsigned char header[8];if(!exact(fd,header,8,0))break;
   if(header[0]!=0x42||header[1]!=0xfa||header[2]!=0x85||header[3]!=0x1f)break;
   unsigned n=(header[4]<<24)|(header[5]<<16)|(header[6]<<8)|header[7];if(n>sizeof(request)||!exact(fd,request,n,0))break;
   unsigned off=0,tag=getvar(request,n,&off),len=getvar(request,n,&off),field=tag>>3;
   if((tag&7)!=2||len>n-off)break;
   unsigned out_size=0,result_size=0;int ok=0;
   if(field==3){memcpy(result,public_pem,public_size);result_size=public_size;ok=1;}
   if(field==1||field==2){unsigned j=off,inner=getvar(request,off+len,&j),size=getvar(request,off+len,&j);
    if(inner==10&&size<=off+len-j){
     if(field==1){size_t sig_size=sizeof(result);EVP_MD_CTX *ctx=EVP_MD_CTX_new();
      ok=ctx&&EVP_DigestSignInit(ctx,0,EVP_sha256(),0,key)==1&&EVP_DigestSign(ctx,result,&sig_size,request+j,size)==1;
      result_size=sig_size;EVP_MD_CTX_free(ctx);
     }else{void *rsa=EVP_PKEY_get1_RSA(key);int got=rsa?RSA_private_decrypt(size,request+j,result,rsa,1):-1;RSA_free(rsa);if(got>=0){ok=1;result_size=got;}}
    }
   }
   if(ok){unsigned k=bytes(nested,1,result,result_size);out_size=bytes(response,field+1,nested,k);}
   else {unsigned char err[]={8,1};out_size=bytes(response,1,err,sizeof(err));}
   printf("operation=%u success=%d bytes=%u\n",field,ok,result_size);
   fflush(0);
   header[4]=out_size>>24;header[5]=out_size>>16;header[6]=out_size>>8;header[7]=out_size;
   if(!exact(fd,header,8,1)||!exact(fd,response,out_size,1))break;
  }close(fd);
 }
}
extern int __libc_start_main(int(*)(int,char**,char**),int,char**,void*,void*,void*,void*);
void start_c(unsigned *stack){__libc_start_main(main,stack[0],(char**)(stack+1),0,0,0,stack);}
__asm__(".text\n.arm\n.global _start\n_start:\nmov r0, sp\nbl start_c\nmov r7, #1\nsvc #0\n");
