/* Uses the private ntdll view tree in virtual_ios.c. */
#include "../checkpoint_view.h"

unsigned int ios_checkpoint_describe_view( uint32_t pid, uintptr_t peb, uintptr_t address,
                                           uint64_t size, uint64_t offset, uint64_t backing,
                                           struct ios_checkpoint_view *out )
{
    sigset_t sigset;
    unsigned int status = STATUS_NOT_SUPPORTED;
    if (!pid || !peb || !out || !size || !backing) return STATUS_INVALID_PARAMETER;
    server_enter_uninterrupted_section( &virtual_mutex, &sigset );
    uintptr_t window = ios_wow_base_for_peb( (void *)peb );
    if (window && address > window && address - window <= UINT32_MAX &&
        size <= (1ULL << 32) - (address - window) && !(address & granularity_mask) &&
        !(offset & granularity_mask) && !(size & host_page_mask))
    {
        struct file_view *view = find_view( (void *)address, size );
        BYTE prot;
        if (view && view->base == (void *)address && view->size == size &&
            view->ios_flags == IOS_VIEW_SHARED_SECTION &&
            get_vprot_range_size( view->base, size, 0xff, &prot ) == size &&
            (prot == (VPROT_COMMITTED | VPROT_READ) ||
             prot == (VPROT_COMMITTED | VPROT_READ | VPROT_WRITE)) &&
            view->protect == (SEC_COMMIT | prot))
        {
            *out = (struct ios_checkpoint_view){1, pid, address - window,
                prot & VPROT_WRITE ? PAGE_READWRITE : PAGE_READONLY, size, offset, backing};
            status = STATUS_SUCCESS;
        }
    }
    server_leave_uninterrupted_section( &virtual_mutex, &sigset );
    return status;
}

unsigned int ios_checkpoint_attach_view( const struct ios_checkpoint_view *record, void *section_handle )
{
    TEB *teb = NtCurrentTeb();
    if (!record || !section_handle || !teb || record->version != 1 || !record->backing ||
        !record->pid || record->pid != HandleToULong(teb->ClientId.UniqueProcess) ||
        !record->guest_base || (record->guest_base & granularity_mask) ||
        !record->size || (record->size & host_page_mask) ||
        record->size > (1ULL << 32) - record->guest_base ||
        record->offset > INT64_MAX - record->size || (record->offset & granularity_mask) ||
        (record->protection != PAGE_READONLY && record->protection != PAGE_READWRITE))
        return STATUS_INVALID_PARAMETER;
    uintptr_t window = ios_wow_base_for_peb( teb->Peb );
    if (!window) return STATUS_NOT_SUPPORTED;
    void *expected = (void *)(window + record->guest_base), *address = expected;
    SIZE_T size = record->size;
    LARGE_INTEGER offset = {.QuadPart = record->offset};
    unsigned int status = NtMapViewOfSection( section_handle, NtCurrentProcess(), &address, 0, 0,
                                              &offset, &size, ViewUnmap, 0, record->protection );
    if (status) return status;
    struct ios_checkpoint_view actual;
    if (address == expected && size == record->size &&
        !ios_checkpoint_describe_view( record->pid, (uintptr_t)teb->Peb, (uintptr_t)address,
                                       size, record->offset, record->backing, &actual ) &&
        actual.protection == record->protection) return STATUS_SUCCESS;
    NtUnmapViewOfSection( NtCurrentProcess(), address );
    return STATUS_CONFLICTING_ADDRESSES;
}
