/* Read-only diagnostic. No debugger attach, suspension, injection, or key scan. */
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <mach-o/ldsyms.h>
#include <libproc.h>
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef kern_return_t (*read_port_fn)(mach_port_name_t, int, mach_port_name_t *);

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    int self = strcmp(argv[1], "self") == 0;
    char *end = NULL;
    long pid = self ? getpid() : strtol(argv[1], &end, 10);
    if ((!self && (!end || *end)) || pid <= 0 || pid > 2147483647) return 2;
    if (!self) {
        char path[PROC_PIDPATHINFO_MAXSIZE] = {0};
        if (proc_pidpath((int)pid, path, sizeof path) <= 0 ||
            strcmp(path, "/Applications/WeChat.app/Contents/MacOS/WeChat") != 0) {
            puts("{\"error\":\"target_is_not_official_app_path\"}");
            return 2;
        }
    }
    read_port_fn fn = (read_port_fn)dlsym(RTLD_DEFAULT, "task_read_for_pid");
    if (!fn) {
        puts("{\"error\":\"read_port_api_unavailable\"}");
        return 2;
    }
    mach_port_t port = MACH_PORT_NULL;
    errno = 0;
    int rc = fn(mach_task_self(), (int)pid, &port);
    int err = errno;
    int readable = 0, magic_ok = 0, read_rc = -999;
    if (rc == KERN_SUCCESS && port != MACH_PORT_NULL) {
        mach_vm_address_t addr = self ? (mach_vm_address_t)&_mh_execute_header : 0;
        int candidate = self;
        for (int i = 0; !self && i < 256; i++) {
            mach_vm_size_t size = 0;
            vm_region_basic_info_data_64_t info;
            mach_msg_type_number_t count = VM_REGION_BASIC_INFO_COUNT_64;
            mach_port_t object = MACH_PORT_NULL;
            read_rc = mach_vm_region(port, &addr, &size, VM_REGION_BASIC_INFO_64,
                                    (vm_region_info_t)&info, &count, &object);
            if (object != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), object);
            if (read_rc != KERN_SUCCESS) break;
            if ((info.protection & (VM_PROT_READ | VM_PROT_EXECUTE)) ==
                (VM_PROT_READ | VM_PROT_EXECUTE)) { candidate = 1; break; }
            if (!size || addr + size <= addr) break;
            addr += size;
        }
        if (candidate) {
            unsigned char header[16] = {0};
            mach_vm_size_t copied = 0;
            read_rc = mach_vm_read_overwrite(port, addr, sizeof header,
                                            (mach_vm_address_t)header, &copied);
            readable = read_rc == KERN_SUCCESS && copied == sizeof header;
            unsigned int magic = 0;
            memcpy(&magic, header, sizeof magic);
            magic_ok = readable && magic == MH_MAGIC_64;
            memset(header, 0, sizeof header);
        }
        mach_port_deallocate(mach_task_self(), port);
    }
    printf("{\"uid\":%d,\"self_test\":%s,\"read_port_result\":%d,"
           "\"errno\":%d,\"read_result\":%d,\"read_16_bytes\":%s,"
           "\"macho_header\":%s,\"key_scan_performed\":false}\n",
           getuid(), self ? "true" : "false", rc, err, read_rc,
           readable ? "true" : "false", magic_ok ? "true" : "false");
    return readable ? 0 : 1;
}
