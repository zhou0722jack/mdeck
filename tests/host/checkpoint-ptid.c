/* Link with the iOS server's process_ios.c. Separate invocations ensure
 * recovery cannot accidentally use the previous process's registry. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "ntstatus.h"
#include "winternl.h"
#include "checkpoint_ptid.h"

extern unsigned int alloc_ptid(void *);
extern void free_ptid(unsigned int);
extern void *get_ptid_entry(unsigned int);
struct thread *current;
unsigned int global_error;

static uint32_t objects[4];

static unsigned int save_id(void *context, uint32_t id, struct object *object)
{
    assert(get_ptid_entry(id) == object);
    return fwrite(&id, sizeof(id), 1, context) == 1 ? 0 : STATUS_UNSUCCESSFUL;
}

static unsigned int create_id(void *context, uint32_t id, struct object **object)
{
    *object = context;
    assert(alloc_ptid(*object) == id);
    return 0;
}

int main(int argc, char **argv)
{
    uint32_t issued;
    assert(argc == 3);
    if (!strcmp(argv[1], "save"))
    {
        FILE *f = fopen(argv[2], "wb");
        assert(f);
        for (unsigned int i = 0; i < 520; ++i)
        {
            unsigned int id = alloc_ptid(&objects[i % 4]);
            if (i != 1 && i != 513) free_ptid(id);
        }
        assert(!ios_checkpoint_capture_ptids(save_id, f, &issued));
        assert(issued == 520 && fwrite(&issued, sizeof(issued), 1, f) == 1);
        assert(!fclose(f));
        return 0;
    }
    FILE *f = fopen(argv[2], "rb");
    uint32_t ids[2];
    assert(f && fread(ids, sizeof(ids), 1, f) == 1 && fread(&issued, sizeof(issued), 1, f) == 1);
    assert(fgetc(f) == EOF && !ferror(f) && !fclose(f));
    assert(ios_checkpoint_restore_ptid(3, create_id, objects) == STATUS_INVALID_PARAMETER);
    for (unsigned int i = 0; i < 2; ++i)
    {
        assert(!ios_checkpoint_restore_ptid(ids[i], create_id, &objects[i]));
        assert(get_ptid_entry(ids[i]) == &objects[i]);
        assert(ios_checkpoint_restore_ptid(ids[i], create_id, objects) == STATUS_INVALID_PARAMETER);
    }
    assert(!ios_checkpoint_finish_ptids(issued));
    assert(!get_ptid_entry(ids[1] + 4));
    assert(alloc_ptid(&objects[2]) == 4 * (issued + 8));
    puts("PASS Wine IDs survive process exit, internal gaps and trailing dead IDs");
}
