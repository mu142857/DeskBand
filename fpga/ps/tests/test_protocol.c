#include "protocol.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static db_command parse_ok(const char *source) {
    char line[80]; db_command command;
    strcpy(line, source);
    assert(db_parse_command(line, &command));
    return command;
}

static void parse_bad(const char *source) {
    char line[80]; db_command command;
    strcpy(line, source);
    assert(!db_parse_command(line, &command));
}

int main(void) {
    db_command c;
    assert(parse_ok("ping\n").type == DB_CMD_PING);
    assert(parse_ok("START").type == DB_CMD_START);
    c = parse_ok("tempo 120"); assert(c.type == DB_CMD_TEMPO && c.value == 120);
    c = parse_ok("MASK 5f beat"); assert(c.value == 0x5f && c.quantization == 1);
    c = parse_ok("pattern 6 a55a"); assert(c.track == 6 && c.value == 0xa55a);
    c = parse_ok("env 3 127 250"); assert(c.track == 3 && c.target == 127 && c.duration == 250);
    c = parse_ok("lfo 2 400000 200"); assert(c.type == DB_CMD_LFO && c.track == 2 && c.value == 0x400000 && c.target == 200);
    c = parse_ok("lfooff 2"); assert(c.type == DB_CMD_LFO_OFF && c.track == 2);
    parse_bad("TEMPO 0"); parse_bad("TEMPO 401"); parse_bad("MASK ff BAR");
    parse_bad("PATTERN 7 1"); parse_bad("ENV 0 256 1"); parse_bad("START extra");
    parse_bad("LFO 0 1000000 1"); parse_bad("LFOOFF 7");
    puts("PASS: UART command protocol parser");
    return 0;
}
