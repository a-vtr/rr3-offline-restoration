#import "RRResourceRuntime.h"
#import <CommonCrypto/CommonDigest.h>
#include <atomic>
#include <sys/file.h>
#include <fcntl.h>
#include <unistd.h>

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #x); exit(2); } } while (0)
static NSString *Container(NSString *root, NSString *name) {
    NSString *p = [root stringByAppendingPathComponent:name];
    NSFileManager *fm = NSFileManager.defaultManager;
    CHECK([fm createDirectoryAtPath:[p stringByAppendingPathComponent:@"Documents"] withIntermediateDirectories:YES attributes:nil error:nil]);
    CHECK([@"host-prototype-only\n" writeToFile:[p stringByAppendingPathComponent:@".rr3-seed-lab"] atomically:YES encoding:NSUTF8StringEncoding error:nil]);
    CHECK([@"progress sentinel" writeToFile:[p stringByAppendingPathComponent:@"Documents/progress.dat"] atomically:YES encoding:NSUTF8StringEncoding error:nil]);
    return p;
}
static void Wait(dispatch_semaphore_t s) {
    CHECK(dispatch_semaphore_wait(s, dispatch_time(DISPATCH_TIME_NOW, 5*NSEC_PER_SEC)) == 0);
}
static NSUInteger Count(NSArray *events, NSString *value) {
    return [[events filteredArrayUsingPredicate:[NSPredicate predicateWithFormat:@"SELF == %@", value]] count];
}
static RRResourceGate *Gate(dispatch_queue_t queue, RRResourceWork work, double timeout,
                            NSMutableArray *events, dispatch_semaphore_t ready,
                            dispatch_semaphore_t failed, NSInteger *lastCode) {
    return [[RRResourceGate alloc] initWithQueue:queue work:work timeout:timeout
        partOne:^{ [events addObject:@"one"]; }
        partTwo:^{ CHECK([events.lastObject isEqual:@"one"]); [events addObject:@"two"]; }
        resume:^{ CHECK([events containsObject:@"two"]); [events addObject:@"resume"]; }
        event:^(NSString *state, NSError *error) {
            [events addObject:state];
            if ([state isEqual:@"ready"]) dispatch_semaphore_signal(ready);
            if ([state isEqual:@"failed"]) { *lastCode = error.code; dispatch_semaphore_signal(failed); }
        }];
}
int main(int argc, const char **argv) {
    @autoreleasepool {
        CHECK(argc == 4);
        NSString *seed = @(argv[1]), *reportPath = @(argv[2]), *root = @(argv[3]);
        NSFileManager *fm = NSFileManager.defaultManager;
        CHECK(![fm fileExistsAtPath:root]);
        CHECK([fm createDirectoryAtPath:root withIntermediateDirectories:YES attributes:nil error:nil]);
        NSDictionary *report = [NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:reportPath] options:0 error:nil];
        NSArray *manifest = report[@"manifest"];
        CHECK(manifest.count == 3);
        RRStopCheck never = ^BOOL { return NO; };
        NSString *c = Container(root, @"restore");
        NSString *cache = [c stringByAppendingPathComponent:@"Library/Caches"];
        CHECK([fm createDirectoryAtPath:cache withIntermediateDirectories:YES attributes:nil error:nil]);
        CHECK([@"save-backup sentinel" writeToFile:[cache stringByAppendingPathComponent:@"player_profile.2.dat.bak"] atomically:YES encoding:NSUTF8StringEncoding error:nil]);
        CHECK([@"unrelated SDK sentinel" writeToFile:[cache stringByAppendingPathComponent:@"unrelated-sdk-state.json"] atomically:YES encoding:NSUTF8StringEncoding error:nil]);
        NSError *error = nil;
        NSDictionary *result = RRRestoreResources(seed,c,manifest,never,&error);
        if (!result) fprintf(stderr,"Backend failure: %ld %s\n",(long)error.code,error.localizedDescription.UTF8String);
        CHECK(result && !error && [result[@"copied"] intValue] == 3);
        result = RRRestoreResources(seed,c,manifest,never,&error);
        CHECK(result && [result[@"retained"] intValue] == 3);
        NSString *target = [[c stringByAppendingPathComponent:@"Library/Caches"] stringByAppendingPathComponent:manifest[0][@"path"]];
        CHECK([fm removeItemAtPath:target error:nil]);
        result = RRRestoreResources(seed,c,manifest,never,&error);
        CHECK(result && [result[@"copied"] intValue] == 1);
        CHECK([@"bad resource" writeToFile:target atomically:YES encoding:NSUTF8StringEncoding error:nil]);
        result = RRRestoreResources(seed,c,manifest,never,&error);
        CHECK(result && [result[@"copied"] intValue] == 1);
        CHECK([[NSString stringWithContentsOfFile:[c stringByAppendingPathComponent:@"Documents/progress.dat"] encoding:NSUTF8StringEncoding error:nil] isEqual:@"progress sentinel"]);
        CHECK([[NSString stringWithContentsOfFile:[cache stringByAppendingPathComponent:@"player_profile.2.dat.bak"] encoding:NSUTF8StringEncoding error:nil] isEqual:@"save-backup sentinel"]);
        CHECK([[NSString stringWithContentsOfFile:[cache stringByAppendingPathComponent:@"unrelated-sdk-state.json"] encoding:NSUTF8StringEncoding error:nil] isEqual:@"unrelated SDK sentinel"]);
        puts("PASS native copy: success, repeated launch, missing/corrupt recovery, progress isolation");

        NSString *interrupted = Container(root,@"interrupted");
        __block int checks = 0;
        error = nil;
        result = RRRestoreResources(seed,interrupted,manifest,^BOOL { return ++checks > 4; },&error);
        CHECK(!result && error.code == 20);
        NSArray *files = [fm subpathsAtPath:interrupted];
        for (NSString *p in files) CHECK([p.lastPathComponent isEqual:@".rr3-seed-lab"] || ![p.lastPathComponent hasPrefix:@".rr3-seed-"]);
        error = nil;
        CHECK(RRRestoreResources(seed,interrupted,manifest,never,&error));
        NSString *badSeed = [root stringByAppendingPathComponent:@"bad-seed"];
        CHECK([fm copyItemAtPath:seed toPath:badSeed error:nil]);
        CHECK([@"bad seed" writeToFile:[badSeed stringByAppendingPathComponent:manifest[0][@"path"]] atomically:YES encoding:NSUTF8StringEncoding error:nil]);
        error = nil;
        CHECK(!RRRestoreResources(badSeed,c,manifest,never,&error) && error.code == 11);
        error = nil;
        CHECK(RRRestoreResources(seed,c,manifest,never,&error));
        NSMutableDictionary *unsafe = [manifest[0] mutableCopy]; unsafe[@"path"] = @"../Documents/progress.dat";
        CHECK(!RRRestoreResources(seed,c,@[unsafe],never,&error));
        NSString *lockPath = [c stringByAppendingPathComponent:@"Library/Application Support/RR3SeedLab/restore.lock"];
        int lock = open(lockPath.fileSystemRepresentation,O_RDWR);
        CHECK(lock >= 0 && flock(lock,LOCK_EX|LOCK_NB)==0);
        error = nil; CHECK(!RRRestoreResources(seed,c,manifest,never,&error) && error.code==30);
        flock(lock,LOCK_UN);close(lock);
        error=nil;CHECK(RRRestoreResources(seed,c,manifest,never,&error));
        NSString *io = Container(root,@"io-error");
        CHECK([fm createDirectoryAtPath:[io stringByAppendingPathComponent:@"Library/Caches"] withIntermediateDirectories:YES attributes:nil error:nil]);
        CHECK([@"blocking file" writeToFile:[io stringByAppendingPathComponent:@"Library/Caches/Tracks"] atomically:YES encoding:NSUTF8StringEncoding error:nil]);
        error=nil;CHECK(!RRRestoreResources(seed,io,manifest,never,&error) && error);
        CHECK([fm removeItemAtPath:[io stringByAppendingPathComponent:@"Library/Caches/Tracks"] error:nil]);
        error=nil;CHECK(RRRestoreResources(seed,io,manifest,never,&error));
        puts("PASS native errors: interruption cleanup/retry, bad seed, path rejection, I/O failure/retry, interprocess lock/retry");

        dispatch_queue_t q = dispatch_queue_create("rr3.lab.control",DISPATCH_QUEUE_SERIAL);
        dispatch_semaphore_t ready=dispatch_semaphore_create(0), failed=dispatch_semaphore_create(0);
        dispatch_semaphore_t entered=dispatch_semaphore_create(0), proceed=dispatch_semaphore_create(0);
        NSMutableArray *events=[NSMutableArray array];
        __block NSInteger code=0;
        __block int attempts=0;
        NSString *gated = Container(root,@"gated");
        RRResourceWork work = ^NSError *(RRStopCheck stop) {
            attempts++; dispatch_semaphore_signal(entered); Wait(proceed);
            NSError *failure=nil;
            CHECK(RRRestoreResources(seed,gated,manifest,stop,&failure) || failure);
            return failure;
        };
        RRResourceGate *gate=Gate(q,work,5,events,ready,failed,&code);
        for(int i=0;i<10;i++) [gate start];
        Wait(entered);
        [gate setActive:YES];[gate setActive:NO];[gate setActive:YES];
        dispatch_sync(q,^{ CHECK(![events containsObject:@"one"]); CHECK(attempts==1); });
        dispatch_semaphore_signal(proceed);Wait(ready);dispatch_sync(q,^{});
        CHECK(Count(events,@"one")==1 && Count(events,@"two")==1 && Count(events,@"resume")==1);
        [gate start];[gate setActive:YES];dispatch_sync(q,^{});CHECK(Count(events,@"resume")==1);
        [gate setActive:NO];[gate setActive:YES];dispatch_sync(q,^{});CHECK(Count(events,@"resume")==2);
        puts("PASS native gate: asynchronous restore, activation coalescing, ordered one-time startup, no concurrent start");

        events=[NSMutableArray array];
        gate=Gate(q,^NSError *(RRStopCheck stop){ (void)stop; return nil; },5,events,ready,failed,&code);
        [gate start];Wait(ready);dispatch_sync(q,^{});CHECK(![events containsObject:@"one"]);
        [gate setActive:YES];dispatch_sync(q,^{});CHECK(Count(events,@"one")==1);
        puts("PASS native gate: resources ready while inactive waits for activation");

        events=[NSMutableArray array];attempts=0;
        gate=Gate(q,^NSError *(RRStopCheck stop){
            (void)stop;
            attempts++;
            return attempts==1 ? [NSError errorWithDomain:@"fixture" code:50 userInfo:nil] : nil;
        },5,events,ready,failed,&code);
        [gate setActive:YES];[gate start];Wait(failed);dispatch_sync(q,^{});
        CHECK(code==50 && ![events containsObject:@"one"]);
        [gate start];Wait(ready);dispatch_sync(q,^{});CHECK(Count(events,@"one")==1 && attempts==2);
        puts("PASS native gate: explicit failure holds engine and retry succeeds");

        events=[NSMutableArray array];attempts=0;
        gate=Gate(q,^NSError *(RRStopCheck stop){
            if (++attempts==1) { dispatch_semaphore_signal(entered);Wait(proceed); }
            return stop() ? [NSError errorWithDomain:@"fixture" code:20 userInfo:nil] : nil;
        },5,events,ready,failed,&code);
        [gate setActive:YES];[gate start];Wait(entered);[gate cancel];Wait(failed);
        CHECK(code==20);[gate start];dispatch_semaphore_signal(proceed);Wait(ready);dispatch_sync(q,^{});
        CHECK(attempts==2 && Count(events,@"one")==1);
        puts("PASS native gate: cancellation, queued retry, stale completion cannot launch engine");

        events=[NSMutableArray array];attempts=0;
        gate=Gate(q,^NSError *(RRStopCheck stop){
            if (++attempts==1) while(!stop()) usleep(1000);
            return stop() ? [NSError errorWithDomain:@"fixture" code:20 userInfo:nil] : nil;
        },0.03,events,ready,failed,&code);
        [gate setActive:YES];[gate start];Wait(failed);CHECK(code==21);
        [gate start];Wait(ready);dispatch_sync(q,^{});CHECK(Count(events,@"one")==1);
        puts("PASS native gate: deadline reports failure, cancels work, and permits safe retry");
        puts("ALL NATIVE HOST TESTS PASSED — no RR3 or iPadOS execution");
    }
    return 0;
}
