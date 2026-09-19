#include "protocol.h"

#include <ctype.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>

static int parse_u32(const char *text, int base, uint32_t maximum, uint32_t *value) {
    char *end = NULL;
    unsigned long parsed;
    if (text == NULL || *text == '\0' || *text == '-') return 0;
    errno = 0;
    parsed = strtoul(text, &end, base);
    if (errno || *end != '\0' || parsed > maximum) return 0;
    *value = (uint32_t)parsed;
    return 1;
}

static int quantization(const char *text, uint8_t *value) {
    if (!strcmp(text, "STEP")) *value = 0;
    else if (!strcmp(text, "BEAT")) *value = 1;
    else if (!strcmp(text, "BAR")) *value = 2;
    else return 0;
    return 1;
}

int db_parse_command(char *line, db_command *command) {
    char *words[5] = {0};
    unsigned count = 0;
    uint32_t a, b, c;
    char *token;

    memset(command, 0, sizeof(*command));
    for (token = strtok(line, " \t\r\n"); token != NULL && count < 5;
         token = strtok(NULL, " \t\r\n")) {
        for (char *p = token; *p; ++p) *p = (char)toupper((unsigned char)*p);
        words[count++] = token;
    }
    if (token != NULL || count == 0) return 0;

    if (count == 1) {
        if (!strcmp(words[0], "PING")) command->type = DB_CMD_PING;
        else if (!strcmp(words[0], "ID")) command->type = DB_CMD_ID;
        else if (!strcmp(words[0], "START")) command->type = DB_CMD_START;
        else if (!strcmp(words[0], "STOP")) command->type = DB_CMD_STOP;
        else if (!strcmp(words[0], "RESET")) command->type = DB_CMD_RESET;
        else if (!strcmp(words[0], "STATUS")) command->type = DB_CMD_STATUS;
        else return 0;
        return 1;
    }
    if (count == 2 && !strcmp(words[0], "TEMPO") &&
        parse_u32(words[1], 10, 400, &a) && a >= 20) {
        command->type = DB_CMD_TEMPO; command->value = a; return 1;
    }
    if (count == 2 && !strcmp(words[0], "CYCLES") &&
        parse_u32(words[1], 0, UINT32_MAX, &a) && a != 0) {
        command->type = DB_CMD_CYCLES; command->value = a; return 1;
    }
    if (count == 2 && !strcmp(words[0], "LFOOFF") && parse_u32(words[1], 10, 6, &a)) {
        command->type = DB_CMD_LFO_OFF; command->track = (uint8_t)a; return 1;
    }
    if (count == 2 && !strcmp(words[0], "VARIATION")) {
        if (!strcmp(words[1], "ON")) a = 1;
        else if (!strcmp(words[1], "OFF")) a = 0;
        else return 0;
        command->type = DB_CMD_VARIATION; command->value = a; return 1;
    }
    if (count == 3 && !strcmp(words[0], "MASK") &&
        parse_u32(words[1], 16, 0x7F, &a) && quantization(words[2], &command->quantization)) {
        command->type = DB_CMD_MASK; command->value = a; return 1;
    }
    if (count == 3 && !strcmp(words[0], "PATTERN") &&
        parse_u32(words[1], 10, 6, &a) && parse_u32(words[2], 16, 0xFFFF, &b)) {
        command->type = DB_CMD_PATTERN; command->track = (uint8_t)a; command->value = b; return 1;
    }
    if (count == 4 && !strcmp(words[0], "ENV") &&
        parse_u32(words[1], 10, 6, &a) && parse_u32(words[2], 10, 255, &b) &&
        parse_u32(words[3], 10, 65535, &c)) {
        command->type = DB_CMD_ENVELOPE; command->track = (uint8_t)a;
        command->target = (uint8_t)b; command->duration = (uint16_t)c; return 1;
    }
    if (count == 4 && !strcmp(words[0], "LFO") &&
        parse_u32(words[1], 10, 6, &a) && parse_u32(words[2], 16, 0xFFFFFF, &b) &&
        parse_u32(words[3], 10, 255, &c)) {
        command->type = DB_CMD_LFO; command->track = (uint8_t)a;
        command->value = b; command->target = (uint8_t)c; return 1;
    }
    return 0;
}
