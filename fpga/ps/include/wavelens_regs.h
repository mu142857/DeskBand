#ifndef WAVELENS_REGS_H
#define WAVELENS_REGS_H

#include <stdint.h>

#define DB_BASE_ADDRESS       UINT32_C(0x43C00000)
#define DB_ID_VERSION         UINT32_C(0x00)
#define DB_CONTROL            UINT32_C(0x04)
#define DB_CYCLES_PER_STEP    UINT32_C(0x08)
#define DB_ABSOLUTE_TICK      UINT32_C(0x0C)
#define DB_APPLIED_MASK       UINT32_C(0x10)
#define DB_MASK_REQUEST       UINT32_C(0x14)
#define DB_BUTTON_STATUS      UINT32_C(0x18)
#define DB_VARIATION_CONTROL  UINT32_C(0x1C)
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
#define DB_VARIATION_STATUS   UINT32_C(0xAC)
#define DB_VARIATION_RANDOM   UINT32_C(0xB0)
#define DB_BAR_INDEX          UINT32_C(0xB4)
#define DB_TAP_STATUS         UINT32_C(0xB8)

#define DB_ID_EXPECTED        UINT32_C(0x44420102)
#define DB_CONTROL_RUN        UINT32_C(0x00000001)
#define DB_CONTROL_RESET      UINT32_C(0x00000002)
#define DB_COMMAND_VALID      UINT32_C(0x80000000)
#define DB_FIFO_OVERFLOW      UINT32_C(0x80000000)
#define DB_ENVELOPE_READY     UINT32_C(0x80000000)
#define DB_TAP_APPLIED        UINT32_C(0x00000100)

#define DB_VARIATION_ENABLE   UINT32_C(0x00000001)
#define DB_VARIATION_ENERGY(status) ((status) & UINT32_C(0x3))
#define DB_VARIATION_LOCKS(status)  (((status) >> 3) & UINT32_C(0x7F))
#define DB_VARIATION_FILL_PENDING(status) (((status) >> 17) & UINT32_C(0x1))
#define DB_VARIATION_FILL_ACTIVE(status)  (((status) >> 18) & UINT32_C(0x1))
#define DB_VARIATION_EIGHTH_ONLY(status)  (((status) >> 19) & UINT32_C(0x1))
#define DB_VARIATION_EIGHTH_PENDING(status) (((status) >> 20) & UINT32_C(0x1))

#endif
