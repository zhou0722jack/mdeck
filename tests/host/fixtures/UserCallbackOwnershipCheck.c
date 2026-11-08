#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>

typedef unsigned int ULONG, DWORD;
typedef int BOOL;
typedef void *HWND;
#define TRUE 1
#define FALSE 0
#define WINE_IOS 1
#define UlongToHandle(h) ((void *)(uintptr_t)(h))
typedef uint64_t ULONG64;
typedef uintptr_t ULONG_PTR;
typedef int NTSTATUS;
typedef void *HINSTANCE;
typedef void *WNDPROC;
typedef struct { WNDPROC procA,procW; } WINDOWPROC;
#define NTUSER_NB_PROCS 8
#define STATUS_DLL_INIT_FAILED ((NTSTATUS)0xc0000142)
#define STATUS_STACK_OVERFLOW ((NTSTATUS)0xc00000fd)
#define STATUS_ACCESS_VIOLATION ((NTSTATUS)0xc0000005)
#define HandleToULong(h) ((DWORD)(uintptr_t)(h))
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define ARRAYSIZE(a) ARRAY_SIZE(a)

typedef struct {
    void *KernelCallbackTable,*LdrData,*ImageBaseAddress,*ProcessParameters;
    void *LoaderLock,*FastPebLock,*TlsBitmap;
    DWORD TlsBitmapBits[2];
} PEB;
typedef struct { PEB *Peb; struct { void *UniqueThread,*UniqueProcess; } ClientId; } TEB;
static TEB *current;
static TEB *NtCurrentTeb(void) { return current; }
struct ntuser_thread_info { DWORD top_window; };
static struct ntuser_thread_info cached_desktop = { 0x10020 };
static HWND get_desktop_window(void);
struct syscall_frame { ULONG64 sp,lr,pc; };
struct callback_stack_layout { void *args; ULONG len,id; ULONG64 lr,sp,pc; unsigned char args_data[]; };
static struct { void *kernel_stack; } thread_data;
static struct { unsigned char reserve[4096]; struct syscall_frame frame; unsigned char stack[8192]; } storage;
static unsigned frame_lookups,dispatches,wrong_callbacks,registrations;
static struct syscall_frame *get_syscall_frame(void) { frame_lookups++; return &storage.frame; }
#define min_kernel_stack 64
#define ntdll_get_thread_data() (&thread_data)
static void *pKiUserCallbackDispatcher = (void *)0x1000;
static void *private_dispatcher = (void *)0x2000;
static void *current_dispatcher;
#define IOS_PFUNC(name) (current_dispatcher)
static void *parent_wow_table[32],*child_ec_table[32],*sibling_native_table[32];

// PRODUCTION_REGISTRY

static NTSTATUS call_user_mode_callback(ULONG64 sp,void **ret_ptr,ULONG *ret_len,void *dispatcher,TEB *teb)
{
    struct callback_stack_layout *stack = (void *)(uintptr_t)sp;
    assert(teb==current&&dispatcher==current_dispatcher&&stack->id==15);
    dispatches++;
    /* Models Wow64KiUserCallbackDispatcher requiring a CPU context. The x64
     * child has none: reaching its inherited launcher's table is the defect. */
    if(teb->Peb->KernelCallbackTable==parent_wow_table) { wrong_callbacks++; return STATUS_ACCESS_VIOLATION; }
    assert(teb->Peb->KernelCallbackTable==child_ec_table||teb->Peb->KernelCallbackTable==sibling_native_table);
    assert(stack->len==3&&!memcmp(stack->args,"abc",3));
    *ret_ptr=stack->args;*ret_len=3;
    return 0;
}

// PRODUCTION_CALLBACK

static void register_builtins(void)
{
    void *result = (void *)1; ULONG count = 9;
    registrations++;
    /* LoadImage and User32 builtin initialization can query the desktop
     * recursively. This must not wait on the mutex held by the same thread. */
    assert(get_desktop_window() == UlongToHandle(cached_desktop.top_window));
    NTSTATUS status = KeUserModeCallback(15,"abc",3,&result,&count);
    if(!status) assert(result&&count==3&&!memcmp(result,"abc",3));
}

// PRODUCTION_BUILTINS
// PRODUCTION_DESKTOP_CACHED
static HWND old_cached_desktop(void) { return UlongToHandle(cached_desktop.top_window); }
/* Build 26 registration order, retained as a negative control without
 * requiring historical Git objects in CI's shallow source checkout. */
static void old_register_builtin_classes(void)
{
    static pthread_mutex_t builtin_lock = PTHREAD_MUTEX_INITIALIZER;
    static struct { DWORD pid; void *peb; } done[128];
    static unsigned int done_count;
    DWORD pid = HandleToULong(NtCurrentTeb()->ClientId.UniqueProcess);
    void *peb = NtCurrentTeb()->Peb;
    unsigned int i;
    pthread_mutex_lock(&builtin_lock);
    for(i=0;i<done_count;i++)
    {
        if(done[i].pid==pid&&done[i].peb==peb) { pthread_mutex_unlock(&builtin_lock);return; }
    }
    register_builtins();
    if(done_count<ARRAYSIZE(done))
    {
        done[done_count].pid=pid;done[done_count].peb=peb;done_count++;
    }
    pthread_mutex_unlock(&builtin_lock);
}
// PRODUCTION_PEB_RESET

static void install_client_procs(PEB *peb,HINSTANCE module)
{
    int i=ios_client_procs_count++;
    assert(i<IOS_MAX_CLIENT_PROCS);
    ios_client_procs_reg[i].peb=peb;ios_client_procs_reg[i].user32_module=module;
}
static void become(TEB *teb,PEB *peb,unsigned pid,void *dispatcher)
{
    *teb=(TEB){.Peb=peb,.ClientId={(void *)(uintptr_t)(pid+1),(void *)(uintptr_t)pid}};
    current=teb;current_dispatcher=dispatcher;
    memset(&storage,0,sizeof(storage));thread_data.kernel_stack=storage.reserve;
    storage.frame.sp=((uintptr_t)(storage.stack+sizeof(storage.stack))-64)&~(uintptr_t)15;
}
int main(void)
{
    TEB child_teb,parent_teb,sibling_teb;
    PEB parent={.KernelCallbackTable=parent_wow_table,.LdrData=(void *)1,.LoaderLock=(void *)2};
    PEB child=parent,sibling=parent;
    become(&child_teb,&child,0xe0,private_dispatcher);
    /* Negative control: Build 26 registers early and reaches the parent's
     * WoW64 callback, even with the correct process-specific EC dispatcher. */
    old_register_builtin_classes();
    assert(registrations==1&&dispatches==1&&wrong_callbacks==1);
    puts("PASS: Build 26 negative control reaches inherited WoW64 callback before child USER32 initialization");
    registrations=dispatches=wrong_callbacks=frame_lookups=0;
    reset_child(&child);
    assert(!child.KernelCallbackTable&&!child.LdrData&&!child.LoaderLock);
    assert(parent.KernelCallbackTable==parent_wow_table&&parent.LoaderLock==(void *)2);
    get_desktop_window();get_desktop_window();
    assert(!registrations&&!dispatches&&!frame_lookups);
    /* Even a non-NULL stale table cannot bypass this process's PFN readiness. */
    child.KernelCallbackTable=parent_wow_table;
    register_builtin_classes();assert(!registrations&&!dispatches);
    child.KernelCallbackTable=NULL;
    void *ret=(void *)1;ULONG length=99;
    assert(KeUserModeCallback(15,NULL,0,&ret,&length)==STATUS_DLL_INIT_FAILED);
    assert(!ret&&!length&&!frame_lookups);
    install_client_procs(&child,(void *)0x3000);
    register_builtin_classes();assert(!registrations);
    child.KernelCallbackTable=child_ec_table;
    assert(old_cached_desktop() && !registrations); /* Build 27's cached path lost the retry. */
    get_desktop_window();get_desktop_window();register_builtin_classes();
    assert(registrations==1&&dispatches==1&&!wrong_callbacks);
    puts("PASS: child callbacks start empty; cached desktop retries deferred registration after own PFNs/callbacks arrive, exactly once without recursive deadlock");
    /* A 32-bit or native sibling with its own PFNs/table keeps working. */
    become(&sibling_teb,&sibling,0xf0,pKiUserCallbackDispatcher);
    reset_child(&sibling);install_client_procs(&sibling,(void *)0x4000);
    sibling.KernelCallbackTable=sibling_native_table;
    register_builtin_classes();register_builtin_classes();
    assert(registrations==2&&dispatches==2&&!wrong_callbacks);
    /* Parent table and PID/PEB-keyed completed child remain untouched. */
    become(&parent_teb,&parent,0x20,pKiUserCallbackDispatcher);
    assert(parent.KernelCallbackTable==parent_wow_table);
    become(&child_teb,&child,0xe0,private_dispatcher);
    register_builtin_classes();assert(registrations==2&&dispatches==2);
    puts("PASS: initialized sibling callbacks remain independent; parent data is preserved and repeated calls do not reregister");
    current=NULL;ret=(void *)1;length=1;
    unsigned before=frame_lookups;
    assert(KeUserModeCallback(15,NULL,0,&ret,&length)==STATUS_DLL_INIT_FAILED&&!ret&&!length);
    assert(KeUserModeCallback(15,NULL,0,NULL,NULL)==STATUS_DLL_INIT_FAILED&&frame_lookups==before);
    TEB empty={0};current=&empty;ret=(void *)1;length=1;
    assert(KeUserModeCallback(15,NULL,0,&ret,&length)==STATUS_DLL_INIT_FAILED&&!ret&&!length);
    puts("PASS: absent TEB/PEB/callback table returns failure before syscall-frame access");
    return 0;
}
