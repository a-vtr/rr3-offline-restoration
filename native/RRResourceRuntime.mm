#import "RRResourceRuntime.h"
#import <CommonCrypto/CommonDigest.h>
#include <atomic>
#include <memory>
#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>
#include <limits.h>
#include <string.h>

static NSError *RRError(NSInteger code, NSString *message) {
    return [NSError errorWithDomain:@"RRResourceLab" code:code
                          userInfo:@{NSLocalizedDescriptionKey:message}];
}
static BOOL RRFail(NSError *__strong *error, NSInteger code, NSString *message) {
    if (error) *error = RRError(code, message);
    return NO;
}
static BOOL RRPlainPath(NSString *path) {
    NSString *cursor = @"/";
    for (NSString *part in path.pathComponents) {
        if ([part isEqual:@"/"]) continue;
        cursor = [cursor stringByAppendingPathComponent:part];
        struct stat s;
        if (lstat(cursor.fileSystemRepresentation, &s) == 0 && S_ISLNK(s.st_mode)) return NO;
    }
    return YES;
}
static BOOL RRNameAllowed(NSString *name) {
    if (![name isKindOfClass:NSString.class] || !name.length || name.isAbsolutePath
        || [name containsString:@"\\"] || [name containsString:[NSString stringWithFormat:@"%C", (unichar)0]]
        || ![name isEqual:name.stringByStandardizingPath] || [name hasSuffix:@".bak"]) return NO;
    NSArray *parts = [name componentsSeparatedByString:@"/"];
    for (NSString *p in parts) if (!p.length || [p isEqual:@".."] || [p isEqual:@"."]) return NO;
    return [@[@"Tracks", @"vehicles", @"gui_assets", @"Shaders"] containsObject:parts.firstObject]
        || [name hasPrefix:@"customisation/textures/"]
        || [@[@"asset_list_base.txtCache.txt", @"asset_list_updates.txt",
              @"asset_list_updates.info", @"tags/app_version", @"SpeedRush_TV_commercial.mp4",
              @"data/upgrade_discount_popups.dat.nct"] containsObject:name];
}
static NSString *RRHash(NSString *path, RRStopCheck stop, NSError *__strong *error) {
    int fd = open(path.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW);
    if (fd < 0) { RRFail(error, 10, @"Cannot open resource"); return nil; }
    struct stat s;
    if (fstat(fd, &s) || !S_ISREG(s.st_mode)) {
        close(fd); RRFail(error, 10, @"Resource is not a regular file"); return nil;
    }
    CC_SHA256_CTX ctx;
    CC_SHA256_Init(&ctx);
    unsigned char buffer[65536], bytes[CC_SHA256_DIGEST_LENGTH];
    while (true) {
        if (stop()) { close(fd); RRFail(error, 20, @"Restoration cancelled"); return nil; }
        ssize_t n = read(fd, buffer, sizeof(buffer));
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) { close(fd); RRFail(error, 10, @"Cannot read resource"); return nil; }
        if (!n) break;
        CC_SHA256_Update(&ctx, buffer, (CC_LONG)n);
    }
    close(fd);
    CC_SHA256_Final(bytes, &ctx);
    NSMutableString *hex = [NSMutableString string];
    for (unsigned char b : bytes) [hex appendFormat:@"%02x", b];
    return hex;
}
static BOOL RRSize(NSString *path, unsigned long long expected) {
    struct stat s;
    return lstat(path.fileSystemRepresentation, &s) == 0 && S_ISREG(s.st_mode)
        && (unsigned long long)s.st_size == expected;
}

static NSDictionary *RRRestoreWithPolicy(NSString *seed, NSString *container,
                                 NSArray<NSDictionary *> *manifest,
                                 RRStopCheck stop, NSError *__strong *error, BOOL experimental) {
    if (error) *error = nil;
    // Foundation standardization can shorten /private/tmp to the /tmp symlink.
    // Use filesystem-canonical roots, while rejecting a caller-supplied leaf symlink.
    struct stat seedStat, containerStat;
    char seedRoot[PATH_MAX], containerRoot[PATH_MAX];
    if (lstat(seed.fileSystemRepresentation, &seedStat) || !S_ISDIR(seedStat.st_mode)
        || lstat(container.fileSystemRepresentation, &containerStat) || !S_ISDIR(containerStat.st_mode)
        || !realpath(seed.fileSystemRepresentation, seedRoot)
        || !realpath(container.fileSystemRepresentation, containerRoot)) {
        RRFail(error, 1, @"Invalid seed/container directories"); return nil;
    }
    seed = [NSString stringWithUTF8String:seedRoot];
    container = [NSString stringWithUTF8String:containerRoot];
    if (!seed.isAbsolutePath || !container.isAbsolutePath || !RRPlainPath(seed) || !RRPlainPath(container)
        || [seed isEqual:container] || [seed hasPrefix:[container stringByAppendingString:@"/"]]
        || [container hasPrefix:[seed stringByAppendingString:@"/"]]) {
        RRFail(error, 1, @"Unsafe seed/container roots"); return nil;
    }
    NSString *marker = [container stringByAppendingPathComponent:@".rr3-seed-lab"];
    if (!experimental && (!RRPlainPath(marker) || ![[NSString stringWithContentsOfFile:marker encoding:NSUTF8StringEncoding error:nil]
                                 isEqual:@"host-prototype-only\n"])) {
        RRFail(error, 1, @"Requires marked scratch container; not a live game importer"); return nil;
    }
    NSString *runtime = [container stringByAppendingPathComponent:@"Library/Caches"];
    NSMutableSet *seen = [NSMutableSet set];
    for (NSDictionary *row in manifest) {
        NSString *name = row[@"path"], *hash = row[@"sha256"];
        NSNumber *size = row[@"bytes"];
        NSCharacterSet *badHex = [[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"] invertedSet];
        if (!RRNameAllowed(name) || [seen containsObject:name]
            || ![hash isKindOfClass:NSString.class] || hash.length != 64
            || [hash rangeOfCharacterFromSet:badHex].location != NSNotFound
            || ![size isKindOfClass:NSNumber.class] || size.longLongValue < 0
            || !RRPlainPath([seed stringByAppendingPathComponent:name])
            || !RRPlainPath([runtime stringByAppendingPathComponent:name])) {
            RRFail(error, 1, @"Invalid resource manifest/path"); return nil;
        }
        [seen addObject:name];
    }
    NSFileManager *fm = NSFileManager.defaultManager;
    NSString *lockDir = [container stringByAppendingPathComponent:experimental
        ? @"Library/Application Support/RR3Restored/ResourceInitialization"
        : @"Library/Application Support/RR3SeedLab"];
    if (!RRPlainPath(runtime) || !RRPlainPath(lockDir)) {
        RRFail(error, 1, @"Symlink runtime/lock directory"); return nil;
    }
    NSError *directoryError = nil;
    if (![fm createDirectoryAtPath:lockDir withIntermediateDirectories:YES attributes:nil error:&directoryError]) {
        if (error) *error = directoryError;
        return nil;
    }
    NSString *lockPath = [lockDir stringByAppendingPathComponent:@"restore.lock"];
    int lockFD = open(lockPath.fileSystemRepresentation, O_CREAT | O_RDWR | O_NOFOLLOW, 0600);
    if (lockFD < 0 || flock(lockFD, LOCK_EX | LOCK_NB)) {
        if (lockFD >= 0) close(lockFD);
        RRFail(error, 30, @"Another restorer holds the resource lock"); return nil;
    }
    __block NSUInteger copied = 0, retained = 0;
    BOOL ok = YES;
    for (NSDictionary *row in manifest) {
        @autoreleasepool {
            NSString *name = row[@"path"], *expected = row[@"sha256"];
            NSString *source = [seed stringByAppendingPathComponent:name];
            NSString *target = [runtime stringByAppendingPathComponent:name];
            unsigned long long size = [row[@"bytes"] unsignedLongLongValue];
            NSString *hash = RRHash(source, stop, error);
            if (!hash || ![hash isEqual:expected] || !RRSize(source, size)) {
                if (hash) RRFail(error, 11, @"Seed integrity failure");
                ok = NO; break;
            }
            if (RRSize(target, size)) {
                NSError *checkError = nil;
                hash = RRHash(target, stop, &checkError);
                if (checkError) { if (error) *error = checkError; ok = NO; break; }
                if ([hash isEqual:expected]) { retained++; continue; }
            }
            NSError *parentError = nil;
            if (![fm createDirectoryAtPath:target.stringByDeletingLastPathComponent
                 withIntermediateDirectories:YES attributes:nil error:&parentError]) {
                if (error) *error = parentError;
                ok = NO; break;
            }
            NSString *templateName = [target.stringByDeletingLastPathComponent stringByAppendingPathComponent:@".rr3-seed-XXXXXX"];
            char *tempName = strdup(templateName.fileSystemRepresentation);
            int output = mkstemp(tempName);
            int input = open(source.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW);
            if (output < 0 || input < 0) {
                if (output >= 0) close(output);
                if (input >= 0) close(input);
                if (output >= 0) unlink(tempName);
                free(tempName); RRFail(error, 10, @"Cannot stage resource"); ok = NO; break;
            }
            unsigned char buffer[65536];
            while (ok) {
                if (stop()) { RRFail(error, 20, @"Restoration cancelled"); ok = NO; break; }
                ssize_t n = read(input, buffer, sizeof(buffer));
                if (n < 0 && errno == EINTR) continue;
                if (n < 0) { RRFail(error, 10, @"Cannot read seed"); ok = NO; break; }
                if (!n) break;
                ssize_t at = 0;
                while (at < n) {
                    ssize_t written = write(output, buffer + at, (size_t)(n - at));
                    if (written < 0 && errno == EINTR) continue;
                    if (written <= 0) { RRFail(error, 10, @"Cannot write resource (check free space)"); ok = NO; break; }
                    at += written;
                }
            }
            if (ok && fsync(output)) { RRFail(error, 10, @"Cannot flush resource"); ok = NO; }
            close(input); close(output);
            NSString *tempPath = [fm stringWithFileSystemRepresentation:tempName length:strlen(tempName)];
            if (ok) {
                hash = RRHash(tempPath, stop, error);
                if (!hash || ![hash isEqual:expected] || !RRSize(tempPath, size)) {
                    if (hash) RRFail(error, 11, @"Staged resource integrity failure");
                    ok = NO;
                }
            }
            if (ok && stop()) { RRFail(error, 20, @"Restoration cancelled"); ok = NO; }
            if (ok && rename(tempName, target.fileSystemRepresentation)) {
                RRFail(error, 10, @"Cannot promote staged resource"); ok = NO;
            }
            if (ok) {
                int parent = open(target.stringByDeletingLastPathComponent.fileSystemRepresentation, O_RDONLY);
                if (parent < 0 || fsync(parent)) { RRFail(error, 10, @"Cannot flush resource directory"); ok = NO; }
                if (parent >= 0) close(parent);
                if (ok) copied++;
            }
            unlink(tempName); free(tempName);
            if (!ok) break;
        }
    }
    flock(lockFD, LOCK_UN); close(lockFD);
    return ok ? @{@"copied":@(copied), @"retained":@(retained)} : nil;
}

NSDictionary *RRRestoreResources(NSString *seed, NSString *container,
        NSArray<NSDictionary *> *manifest, RRStopCheck stop, NSError *__strong *error) {
    return RRRestoreWithPolicy(seed, container, manifest, stop, error, NO);
}

NSDictionary *RRRestoreExperimentalSeed(NSString *seed, NSArray<NSDictionary *> *manifest,
        RRStopCheck stop, NSError *__strong *error) {
    NSString *identity = NSBundle.mainBundle.bundleIdentifier;
    NSString *prefix = @"org.rr3preservation.restored";
    if (!([identity isEqual:prefix] || [identity hasPrefix:[prefix stringByAppendingString:@"."]])) {
        RRFail(error, 1, @"Restorer refused non-experimental application identity"); return nil;
    }
    NSString *home = NSHomeDirectory();
    NSError *cacheError = nil;
    NSURL *cache = [NSFileManager.defaultManager URLForDirectory:NSCachesDirectory
        inDomain:NSUserDomainMask appropriateForURL:nil create:YES error:&cacheError];
    // Do not accept a supplied or shared-group container. Both APIs must agree.
    NSString *expected = [home stringByAppendingPathComponent:@"Library/Caches"];
    if (!cache || ![cache.path.stringByResolvingSymlinksInPath isEqual:expected.stringByResolvingSymlinksInPath]) {
        if (cacheError) { if (error) *error = cacheError; return nil; }
        RRFail(error, 1, @"Private cache-directory mapping mismatch"); return nil;
    }
    return RRRestoreWithPolicy(seed, home, manifest, stop, error, YES);
}

struct RRJob { std::atomic<bool> stop{false}; };
@implementation RRResourceGate {
    dispatch_queue_t _control, _worker;
    RRResourceWork _work;
    dispatch_block_t _one, _two, _resume;
    void (^_event)(NSString *, NSError *);
    NSTimeInterval _timeout;
    BOOL _running, _ready, _started, _active, _failed, _retryPending;
    std::shared_ptr<RRJob> _job;
}
- (instancetype)initWithQueue:(dispatch_queue_t)queue work:(RRResourceWork)work
                      timeout:(NSTimeInterval)timeout partOne:(dispatch_block_t)one
                      partTwo:(dispatch_block_t)two resume:(dispatch_block_t)resume
                        event:(void (^)(NSString *, NSError *))event {
    if ((self = [super init])) {
        _control = queue;
        _worker = dispatch_queue_create("rr3.seed.worker", DISPATCH_QUEUE_SERIAL);
        _work = [work copy]; _one = [one copy]; _two = [two copy]; _resume = [resume copy];
        _event = [event copy]; _timeout = timeout;
    }
    return self;
}
- (void)maybeLaunch {
    if (_ready && _active && !_started) {
        _started = YES;
        _one(); _two(); _resume();
    }
}
- (void)begin {
    if (_ready) return;
    if (_running) { if (_failed) _retryPending = YES; return; }
    if (_timeout <= 0) { _event(@"failed", RRError(1, @"Invalid initialization deadline")); return; }
    _failed = NO; _running = YES; _retryPending = NO;
    auto job = std::make_shared<RRJob>(); _job = job;
    _event(@"restoring", nil);
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(_timeout * NSEC_PER_SEC)), _control, ^{
        if (self->_job == job && self->_running && !self->_failed) {
            job->stop = true; self->_failed = YES;
            self->_event(@"failed", RRError(21, @"Initialization deadline exceeded; engine held"));
        }
    });
    dispatch_async(_worker, ^{
        @autoreleasepool {
            NSError *failure = nil;
            @try { failure = self->_work(^BOOL { return job->stop.load(); }); }
            @catch (NSException *) { failure = RRError(10, @"Initialization worker failed; engine held"); }
            dispatch_async(self->_control, ^{
                if (self->_job != job) return;
                self->_running = NO;
                if (!self->_failed) {
                    if (failure || job->stop) {
                        self->_failed = YES;
                        self->_event(@"failed", failure ?: RRError(20, @"Restoration cancelled"));
                    } else {
                        self->_ready = YES; self->_event(@"ready", nil); [self maybeLaunch];
                    }
                }
                if (self->_retryPending && !self->_ready) [self begin];
            });
        }
    });
}
- (void)start { dispatch_async(_control, ^{ [self begin]; }); }
- (void)setActive:(BOOL)active {
    dispatch_async(_control, ^{
        BOOL changed = self->_active != active;
        self->_active = active;
        BOOL wasStarted = self->_started;
        [self maybeLaunch];
        if (changed && active && wasStarted && self->_ready) self->_resume();
    });
}
- (void)cancel {
    dispatch_async(_control, ^{
        if (self->_running && !self->_failed) {
            self->_job->stop = true; self->_failed = YES;
            self->_event(@"failed", RRError(20, @"Restoration cancelled; retry available"));
        }
    });
}
@end
