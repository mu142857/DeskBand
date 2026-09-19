#include "deskband_regs.h"
#include "protocol.h"

#include "xil_io.h"
#include "xil_printf.h"
#include "xparameters.h"
#include "xuartps_hw.h"

#include <stdint.h>

#define UART_BASE XPAR_XUARTPS_0_BASEADDR
#define INPUT_CAPACITY 96

static inline uint32_t reg_read(uint32_t offset) { return Xil_In32(DB_BASE_ADDRESS + offset); }
static inline void reg_write(uint32_t offset, uint32_t value) { Xil_Out32(DB_BASE_ADDRESS + offset, value); }

static void report_status(void) {
    uint32_t variation = reg_read(DB_VARIATION_STATUS);
    xil_printf("ST run=%u tick=%u mask=%02x fifo=%u overflow=%u variation=%u energy=%u\r\n",
        reg_read(DB_CONTROL) & 1u, reg_read(DB_ABSOLUTE_TICK),
        reg_read(DB_APPLIED_MASK) & 0x7fu, reg_read(DB_STATUS) & 0xffu,
        reg_read(DB_STATUS) >> 31, reg_read(DB_VARIATION_CONTROL) & 1u,
        DB_VARIATION_ENERGY(variation));
}

static void execute(const db_command *command) {
    uint32_t value;
    switch (command->type) {
    case DB_CMD_PING: xil_printf("PONG DB01\r\n"); break;
    case DB_CMD_ID: xil_printf("ID %08x\r\n", reg_read(DB_ID_VERSION)); break;
    case DB_CMD_START: reg_write(DB_CONTROL, DB_CONTROL_RUN); xil_printf("OK START\r\n"); break;
    case DB_CMD_STOP: reg_write(DB_CONTROL, 0); xil_printf("OK STOP\r\n"); break;
    case DB_CMD_RESET:
        value = reg_read(DB_CONTROL) & DB_CONTROL_RUN;
        reg_write(DB_CONTROL, value | DB_CONTROL_RESET); xil_printf("OK RESET\r\n"); break;
    case DB_CMD_STATUS: report_status(); break;
    case DB_CMD_TEMPO:
        value = UINT32_C(1500000000) / command->value;
        reg_write(DB_CYCLES_PER_STEP, value); xil_printf("OK TEMPO %u %u\r\n", command->value, value); break;
    case DB_CMD_CYCLES:
        reg_write(DB_CYCLES_PER_STEP, command->value); xil_printf("OK CYCLES %u\r\n", command->value); break;
    case DB_CMD_MASK:
        reg_write(DB_MASK_REQUEST, DB_COMMAND_VALID | ((uint32_t)command->quantization << 8) | command->value);
        xil_printf("OK MASK %02x %u\r\n", command->value, command->quantization); break;
    case DB_CMD_PATTERN:
        reg_write(DB_PATTERN(command->track), command->value);
        xil_printf("OK PATTERN %u %04x\r\n", command->track, command->value); break;
    case DB_CMD_ENVELOPE:
        if (!(reg_read(DB_ENVELOPE_ACTIVE) & DB_ENVELOPE_READY)) { xil_printf("BUSY ENV\r\n"); break; }
        value = ((uint32_t)command->duration << 16) | ((uint32_t)command->target << 8) | command->track;
        reg_write(DB_ENVELOPE_COMMAND, value);
        xil_printf("OK ENV %u %u %u\r\n", command->track, command->target, command->duration); break;
    case DB_CMD_LFO:
        reg_write(DB_LFO_INCREMENT, command->value);
        value = DB_COMMAND_VALID | (1u << 30) | (1u << 29) |
                ((uint32_t)command->target << 21) | command->track;
        reg_write(DB_LFO_COMMAND, value);
        xil_printf("OK LFO %u %06x %u\r\n", command->track, command->value, command->target); break;
    case DB_CMD_LFO_OFF:
        reg_write(DB_LFO_COMMAND, DB_COMMAND_VALID | command->track);
        xil_printf("OK LFOOFF %u\r\n", command->track); break;
    case DB_CMD_VARIATION:
        reg_write(DB_VARIATION_CONTROL, command->value & DB_VARIATION_ENABLE);
        if (command->value)
            xil_printf("OK VARIATION ON\r\n");
        else
            xil_printf("OK VARIATION OFF\r\n");
        break;
    default: xil_printf("ERR INTERNAL\r\n"); break;
    }
}

static void drain_events(void) {
    uint32_t status, low, high;
    while (((status = reg_read(DB_STATUS)) & 0xffu) != 0) {
        low = reg_read(DB_EVENT_LO); high = reg_read(DB_EVENT_HI);
        xil_printf("EV %u %u %02x %02x %u\r\n", low, high & 0xfu,
            (high >> 4) & 0x7fu, (high >> 11) & 0x7fu, (high >> 18) & 1u);
    }
    if (status & DB_FIFO_OVERFLOW) {
        xil_printf("ERR FIFO_OVERFLOW\r\n"); reg_write(DB_STATUS, DB_FIFO_OVERFLOW);
    }
}

static void report_controls(void) {
    static uint32_t previous_buttons;
    static uint8_t previous_levels[7] = {255,255,255,255,255,255,255};
    static uint8_t previous_lfos[7];
    uint8_t levels[7], lfos[7];
    int controls_changed = 0;
    uint32_t buttons = reg_read(DB_BUTTON_STATUS);
    if ((buttons & 0x000f0f00u) != 0) {
        uint32_t presses = (buttons >> 8) & 0xfu;
        /* BTN0/BTN1 are forwarded to the Mac as shutter/math. BTN2 changes
         * the PL rhythm grid and BTN3 is measured by the PL tap-tempo unit. */
        xil_printf("BTN %x %x %x %x\r\n", buttons & 0xfu, presses,
                   (buttons >> 16) & 0xfu, (buttons >> 24) & 0xfu);
        reg_write(DB_BUTTON_STATUS, buttons & 0x000f0f00u);
    } else if ((buttons & 0xfu) != previous_buttons) {
        xil_printf("BTN %x 0 0 %x\r\n", buttons & 0xfu,
                   (buttons >> 24) & 0xfu);
    }
    previous_buttons = buttons & 0xfu;

    for (unsigned track = 0; track < 7; ++track) {
        levels[track] = (uint8_t)reg_read(DB_LEVEL(track));
        lfos[track] = (uint8_t)reg_read(DB_LFO_VALUE(track));
        if (levels[track] != previous_levels[track] || lfos[track] != previous_lfos[track])
            controls_changed = 1;
        previous_levels[track] = levels[track]; previous_lfos[track] = lfos[track];
    }
    if (controls_changed) {
        xil_printf("CV %u %u %u %u %u %u %u %u %u %u %u %u %u %u\r\n",
            levels[0], levels[1], levels[2], levels[3], levels[4], levels[5], levels[6],
            lfos[0], lfos[1], lfos[2], lfos[3], lfos[4], lfos[5], lfos[6]);
    }
}

static void report_tap_tempo(void) {
    uint32_t status = reg_read(DB_TAP_STATUS);
    if (status & DB_TAP_APPLIED) {
        uint32_t cycles = reg_read(DB_CYCLES_PER_STEP);
        uint32_t bpm = (UINT32_C(1500000000) + cycles / 2u) / cycles;
        xil_printf("TAP %u\r\n", bpm);
        reg_write(DB_TAP_STATUS, DB_TAP_APPLIED);
    }
}

static void report_variation(void) {
    static uint32_t previous_bar = UINT32_MAX;
    static uint32_t previous_status = UINT32_MAX;
    uint32_t bar = reg_read(DB_BAR_INDEX);
    uint32_t status = reg_read(DB_VARIATION_STATUS);
    if (bar != previous_bar || status != previous_status) {
        xil_printf("BAR %u %u %02x %u %u %u %04x %u %u\r\n",
            bar, DB_VARIATION_ENERGY(status), DB_VARIATION_LOCKS(status),
            DB_VARIATION_FILL_ACTIVE(status), DB_VARIATION_FILL_PENDING(status),
            reg_read(DB_VARIATION_CONTROL) & 1u,
            reg_read(DB_VARIATION_RANDOM) & 0xffffu,
            DB_VARIATION_EIGHTH_ONLY(status),
            DB_VARIATION_EIGHTH_PENDING(status));
        previous_bar = bar;
        previous_status = status;
    }
}

int main(void) {
    char line[INPUT_CAPACITY]; unsigned length = 0;
    if (reg_read(DB_ID_VERSION) != DB_ID_EXPECTED) {
        xil_printf("FATAL PL_ID %08x\r\n", reg_read(DB_ID_VERSION));
        return 1;
    }
    xil_printf("READY DESKBAND 1.0\r\n");
    for (;;) {
        if (XUartPs_IsReceiveData(UART_BASE)) {
            char ch = (char)XUartPs_ReadReg(UART_BASE, XUARTPS_FIFO_OFFSET);
            if (ch == '\r' || ch == '\n') {
                if (length != 0) {
                    db_command command; line[length] = '\0';
                    if (db_parse_command(line, &command)) execute(&command);
                    else xil_printf("ERR COMMAND\r\n");
                    length = 0;
                }
            } else if (length + 1 < INPUT_CAPACITY) line[length++] = ch;
            else { length = 0; xil_printf("ERR LINE_TOO_LONG\r\n"); }
        }
        drain_events();
        report_controls();
        report_tap_tempo();
        report_variation();
    }
}
