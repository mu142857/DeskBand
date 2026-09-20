/* WaveLens.app main executable.
 *
 * A shell script cannot be the bundle's executable: the running process would
 * be /bin/bash, and macOS would not attribute the camera request to WaveLens
 * (no prompt, no access). This small native program is the app's process; it
 * starts Python as a child and waits, so the child inherits WaveLens as its
 * responsible app and the permission prompt carries WaveLens's name.
 *
 * Built by tools/build_app.sh with -DROOT="\"/path/to/project\"".
 */
#include <fcntl.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef ROOT
#error "build with -DROOT=\"...\""
#endif

extern char **environ;

int main(void) {
    const char *python = ROOT "/.venv/bin/python";
    const char *script = ROOT "/main.py";
    const char *logfile = ROOT "/cache/wavelens.log";

    if (chdir(ROOT) != 0) {
        perror("chdir");
        return 1;
    }
    setenv("SSL_CERT_FILE", ROOT "/.venv/lib/python3.11/site-packages/certifi/cacert.pem", 0);
    setenv("PYTHONUNBUFFERED", "1", 1);

    /* Optional, project-local credential. Keep it out of launchctl and Git;
     * Python still receives it only through its process environment. */
    if (getenv("ELEVENLABS_API_KEY") == NULL) {
        int keyfd = open(ROOT "/cache/elevenlabs_api_key", O_RDONLY | O_NOFOLLOW);
        if (keyfd >= 0) {
            struct stat info;
            if (fstat(keyfd, &info) == 0 && S_ISREG(info.st_mode) &&
                info.st_uid == geteuid() && (info.st_mode & 0077) == 0) {
                char key[256] = {0};
                ssize_t length = read(keyfd, key, sizeof(key) - 1);
                if (length > 0) {
                    key[strcspn(key, "\r\n")] = '\0';
                    if (key[0] != '\0') setenv("ELEVENLABS_API_KEY", key, 0);
                }
                memset(key, 0, sizeof(key));
            }
            close(keyfd);
        }
    }

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
