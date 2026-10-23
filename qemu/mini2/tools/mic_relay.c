/* Pull raw stereo S16_LE/48kHz from the local Mac capture bridge. */
extern int socket(int,int,int),connect(int,const void*,unsigned),close(int),read(int,void*,unsigned),write(int,const void*,unsigned),open(const char*,int,...),mkfifo(const char*,unsigned),sleep(unsigned),printf(const char*,...),fflush(void*);
extern void *signal(int,void*);
int main(int argc,char **argv,char **env) {
 (void)argc;(void)argv;(void)env;
 signal(13,(void*)1);
 mkfifo("/tmp/mac-microphone.pcm",0600);
 int fifo=open("/tmp/mac-microphone.pcm",2);if(fifo<0)return 2;
 const unsigned char address[16]={2,0,0x4a,0x95,10,0,2,2,0,0,0,0,0,0,0,0};
 char data[8192];unsigned total=0;
 for(;;){int fd=socket(2,1,0);if(fd<0||connect(fd,address,16)<0){if(fd>=0)close(fd);sleep(2);continue;}
  printf("Microphone TCP connected\n");fflush(0);
  int n;while((n=read(fd,data,sizeof(data)))>0){int offset=0;while(offset<n){int got=write(fifo,data+offset,n-offset);if(got<=0)break;offset+=got;}total+=n;if(total>=1920000){printf("Microphone delivered 10 seconds of PCM\n");fflush(0);total=0;}}
  close(fd);sleep(1);
 }
}
extern int __libc_start_main(int(*)(int,char**,char**),int,char**,void*,void*,void*,void*);
void start_c(unsigned *stack){__libc_start_main(main,stack[0],(char**)(stack+1),0,0,0,stack);}
__asm__(".text\n.arm\n.global _start\n_start:\nmov r0, sp\nbl start_c\nmov r7, #1\nsvc #0\n");
