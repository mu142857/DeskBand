/* DeskBand.app main executable.
 *
 * A shell script cannot be the bundle's executable: the running process would
 * be /bin/bash, and macOS would not attribute the camera request to DeskBand
 * (no prompt, no access). This small native program is the app's process; it
 * starts Python as a child and waits, so the child inherits DeskBand as its
 * responsible app and the permission prompt carries DeskBand's name.
 *
 * Built by tools/build_app.sh with -DROOT="\"/path/to/project\"".
 */
#include <fcntl.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef ROOT
#error "build with -DROOT=\"...\""
#endif

extern char **environ;

int main(void) {
    const char *python = ROOT "/.venv/bin/python";
    const char *script = ROOT "/main.py";
    const char *logfile = ROOT "/cache/deskband.log";

    if (chdir(ROOT) != 0) {
        perror("chdir");
        return 1;
    }
    setenv("SSL_CERT_FILE", ROOT "/.venv/lib/python3.11/site-packages/certifi/cacert.pem", 0);
    setenv("PYTHONUNBUFFERED", "1", 1);

    posix_spawn_file_actions_t fa;
    posix_spawn_file_actions_init(&fa);
    posix_spawn_file_actions_addopen(&fa, STDOUT_FILENO, logfile, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    posix_spawn_file_actions_adddup2(&fa, STDOUT_FILENO, STDERR_FILENO);

    char *argv[] = {(char *)python, (char *)script, NULL};
    pid_t pid;
    int rc = posix_spawn(&pid, python, &fa, NULL, argv, environ);
    if (rc != 0) {
        fprintf(stderr, "could not start %s (error %d)\n", python, rc);
        return 1;
    }
    int status = 0;
    waitpid(pid, &status, 0);
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
