#ifndef DESKBAND_PROTOCOL_H
#define DESKBAND_PROTOCOL_H

#include <stdint.h>

typedef enum {
    DB_CMD_INVALID = 0,
    DB_CMD_PING,
    DB_CMD_ID,
    DB_CMD_START,
    DB_CMD_STOP,
    DB_CMD_RESET,
    DB_CMD_STATUS,
    DB_CMD_TEMPO,
    DB_CMD_CYCLES,
    DB_CMD_MASK,
    DB_CMD_PATTERN,
    DB_CMD_ENVELOPE,
    DB_CMD_LFO,
    DB_CMD_LFO_OFF
} db_command_type;

typedef struct {
    db_command_type type;
    uint32_t value;
    uint16_t duration;
    uint8_t track;
    uint8_t target;
    uint8_t quantization;
} db_command;

int db_parse_command(char *line, db_command *command);

#endif
