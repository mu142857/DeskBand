#ifndef DESKBAND_REGS_H
#define DESKBAND_REGS_H

#include <stdint.h>

#define DB_BASE_ADDRESS       UINT32_C(0x43C00000)
#define DB_ID_VERSION         UINT32_C(0x00)
#define DB_CONTROL            UINT32_C(0x04)
#define DB_CYCLES_PER_STEP    UINT32_C(0x08)
#define DB_ABSOLUTE_TICK      UINT32_C(0x0C)
#define DB_APPLIED_MASK       UINT32_C(0x10)
#define DB_MASK_REQUEST       UINT32_C(0x14)
#define DB_BUTTON_STATUS      UINT32_C(0x18)
#define DB_PATTERN(track)     (UINT32_C(0x20) + UINT32_C(4) * (track))
#define DB_STATUS             UINT32_C(0x40)
#define DB_EVENT_LO           UINT32_C(0x48)
#define DB_EVENT_HI           UINT32_C(0x4C)
#define DB_ENVELOPE_ACTIVE    UINT32_C(0x58)
#define DB_ENVELOPE_COMMAND   UINT32_C(0x5C)
#define DB_LEVEL(track)       (UINT32_C(0x60) + UINT32_C(4) * (track))
#define DB_LFO_COMMAND        UINT32_C(0x80)
#define DB_LFO_INCREMENT      UINT32_C(0x84)
#define DB_LFO_STATUS         UINT32_C(0x88)
#define DB_LFO_VALUE(track)   (UINT32_C(0x90) + UINT32_C(4) * (track))

#define DB_ID_EXPECTED        UINT32_C(0x44420100)
#define DB_CONTROL_RUN        UINT32_C(0x00000001)
#define DB_CONTROL_RESET      UINT32_C(0x00000002)
#define DB_COMMAND_VALID      UINT32_C(0x80000000)
#define DB_FIFO_OVERFLOW      UINT32_C(0x80000000)
#define DB_ENVELOPE_READY     UINT32_C(0x80000000)

#endif
