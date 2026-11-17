#import <Foundation/Foundation.h>
#import <dispatch/dispatch.h>

NS_ASSUME_NONNULL_BEGIN
typedef BOOL (^RRStopCheck)(void);
// Lab-only native backend. Requires .rr3-seed-lab in a separate scratch container.
// Strong error output preserves failures across per-file autorelease pools.
NSDictionary * _Nullable RRRestoreResources(NSString *seed, NSString *container,
    NSArray<NSDictionary *> *manifest, RRStopCheck stop, NSError *__strong *error);
// Experimental game entry: only this process's dynamically discovered container,
// and only the separately identified RR3 Restored bundle. No lab-marker bypass
// is exposed for arbitrary containers.
NSDictionary * _Nullable RRRestoreExperimentalSeed(NSString *seed,
    NSArray<NSDictionary *> *manifest, RRStopCheck stop, NSError *__strong *error);

typedef NSError * _Nullable (^RRResourceWork)(RRStopCheck stop);
// controlQueue must be serial (main queue for a future UIKit adapter).
// No RR3 swizzling, load-command editing or UIKit integration is performed here.
@interface RRResourceGate : NSObject
- (instancetype)initWithQueue:(dispatch_queue_t)controlQueue
                         work:(RRResourceWork)work
                      timeout:(NSTimeInterval)timeout
                      partOne:(dispatch_block_t)one
                      partTwo:(dispatch_block_t)two
                       resume:(dispatch_block_t)resume
                        event:(void (^)(NSString *, NSError * _Nullable))event;
- (void)start;
- (void)setActive:(BOOL)active;
- (void)cancel;
@end
NS_ASSUME_NONNULL_END
