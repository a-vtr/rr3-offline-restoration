#import <UIKit/UIKit.h>
#import "RRResourceRuntime.h"
#include <unistd.h>

@interface RRLabViewController : UIViewController
- (void)setLabActive:(BOOL)active;
@end

@implementation RRLabViewController {
    UITextView *_log;
    UILabel *_status;
    UIActivityIndicatorView *_spinner;
    RRResourceGate *_gate;
    NSArray<NSDictionary *> *_manifest;
    NSString *_seed, *_container, *_evidence;
    NSMutableArray *_events;
    NSUInteger _partOne, _partTwo, _resumes, _heartbeats;
    BOOL _ready, _busy, _active;
    NSTimer *_timer;
}
- (void)record:(NSString *)message {
    NSAssert(NSThread.isMainThread, @"Lab callbacks must run on main thread");
    [_events addObject:@{@"event":message, @"time":@([NSDate timeIntervalSinceReferenceDate])}];
    _log.text = [_log.text stringByAppendingFormat:@"%@\n", message];
    if (_log.text.length) [_log scrollRangeToVisible:NSMakeRange(_log.text.length-1,1)];
    NSDictionary *result = @{@"scope":@"UIKit resource lab; simulated game only",
        @"os":UIDevice.currentDevice.systemVersion, @"deviceClass":UIDevice.currentDevice.model,
        @"build":NSBundle.mainBundle.infoDictionary[@"RRBuildID"] ?: @"unknown",
        @"partOne":@(_partOne), @"partTwo":@(_partTwo), @"resume":@(_resumes),
        @"mainRunLoopHeartbeats":@(_heartbeats), @"events":_events};
    NSData *json = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:nil];
    [json writeToFile:_evidence atomically:YES];
}
- (UIButton *)button:(NSString *)title action:(SEL)action {
    UIButton *b = [UIButton buttonWithType:UIButtonTypeSystem];
    [b setTitle:title forState:UIControlStateNormal];
    [b addTarget:self action:action forControlEvents:UIControlEventTouchUpInside];
    return b;
}
- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.systemBackgroundColor;
    self.title = @"RR3 Resource Lab";
    _events = [NSMutableArray array];
    _status = [UILabel new]; _status.numberOfLines=0; _status.text=@"Preparing local resource test";
    _spinner = [[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium];
    _log = [UITextView new]; _log.editable=NO; _log.text=@"";
    _log.font=[UIFont monospacedSystemFontOfSize:13 weight:UIFontWeightRegular];
    UIStackView *controls = [[UIStackView alloc] initWithArrangedSubviews:@[
        [self button:@"Run / retry" action:@selector(run)],
        [self button:@"Cancel" action:@selector(cancel)],
        [self button:@"Simulate activation" action:@selector(simulateActivation)],
        [self button:@"Repair missing test file" action:@selector(testMissing)],
        [self button:@"Repair corrupt test file" action:@selector(testCorrupt)]]];
    controls.axis=UILayoutConstraintAxisVertical; controls.spacing=6;
    UIStackView *stack=[[UIStackView alloc] initWithArrangedSubviews:@[_status,_spinner,controls,_log]];
    stack.axis=UILayoutConstraintAxisVertical;stack.spacing=8;stack.translatesAutoresizingMaskIntoConstraints=NO;
    [self.view addSubview:stack];
    UILayoutGuide *safe=self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [stack.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor constant:16],
        [stack.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor constant:-16],
        [stack.topAnchor constraintEqualToAnchor:safe.topAnchor constant:12],
        [stack.bottomAnchor constraintEqualToAnchor:safe.bottomAnchor constant:-12],
        [_log.heightAnchor constraintGreaterThanOrEqualToConstant:120]]];
    _seed=[NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"ResourceSeed"];
    NSData *data=[NSData dataWithContentsOfFile:[NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"seed-manifest.json"]];
    _manifest=data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    NSError *error=nil;
    NSURL *support=[NSFileManager.defaultManager URLForDirectory:NSApplicationSupportDirectory
        inDomain:NSUserDomainMask appropriateForURL:nil create:YES error:&error];
    if (!support) { _status.text=@"Cannot create application support directory"; return; }
    NSString *root=[support.path stringByAppendingPathComponent:@"RR3NativeResourceLab"];
    _container=[root stringByAppendingPathComponent:@"scratch"];
    [NSFileManager.defaultManager createDirectoryAtPath:[_container stringByAppendingPathComponent:@"Documents"]
        withIntermediateDirectories:YES attributes:nil error:&error];
    _evidence=[root stringByAppendingPathComponent:@"latest-result.json"];
    [@"host-prototype-only\n" writeToFile:[_container stringByAppendingPathComponent:@".rr3-seed-lab"]
        atomically:YES encoding:NSUTF8StringEncoding error:&error];
    NSString *progress=[_container stringByAppendingPathComponent:@"Documents/progress-sentinel.txt"];
    if (![NSFileManager.defaultManager fileExistsAtPath:progress])
        [@"synthetic lab progress — preserve\n" writeToFile:progress atomically:YES encoding:NSUTF8StringEncoding error:&error];
    if (error || ![_manifest isKindOfClass:NSArray.class] || !_manifest.count) {
        _status.text=@"Setup failed: resource seed/manifest or writable directory unavailable";
        return;
    }
    __weak RRLabViewController *weakSelf=self;
    _timer=[NSTimer scheduledTimerWithTimeInterval:0.1 repeats:YES block:^(NSTimer *){
        RRLabViewController *s=weakSelf;
        if (s && s->_busy) s->_heartbeats++;
    }];
    [self record:@"UIKit lab ready; no network or RR3 code is used"];
    [self makeGate];[self run];
}
- (void)makeGate {
    _ready=NO;_partOne=0;_partTwo=0;_resumes=0;_heartbeats=0;
    NSString *seed=_seed,*container=_container;NSArray *manifest=_manifest;
    __weak RRLabViewController *weakSelf=self;
    _gate=[[RRResourceGate alloc] initWithQueue:dispatch_get_main_queue()
        work:^NSError *(RRStopCheck stop){
            // Lab-only delay lets activation/cancellation and UI responsiveness be observed.
            for (int i=0;i<100;i++) {
                if (stop()) return [NSError errorWithDomain:@"RRLab" code:20 userInfo:@{NSLocalizedDescriptionKey:@"Cancelled"}];
                usleep(20000);
            }
            NSError *error=nil;
            NSDictionary *result=RRRestoreResources(seed,container,manifest,stop,&error);
            return result ? nil : (error ?: [NSError errorWithDomain:@"RRLab" code:10 userInfo:@{NSLocalizedDescriptionKey:@"Restoration failed"}]);
        } timeout:30
        partOne:^{ RRLabViewController *s=weakSelf;if (!s) return;
            NSAssert(s->_ready,@"Game initialization preceded resource readiness");
            s->_partOne++;[s record:@"SIMULATED constructPartOne after verified restoration"]; }
        partTwo:^{ RRLabViewController *s=weakSelf;if (!s) return;
            NSAssert(s->_ready && s->_partOne==1,@"Invalid construction order");
            s->_partTwo++;[s record:@"SIMULATED constructPartTwo"]; }
        resume:^{ RRLabViewController *s=weakSelf;if (!s) return;
            NSAssert(s->_ready && s->_partTwo==1,@"Resume preceded construction");
            s->_resumes++;
            s->_status.text=@"PASS: local resources verified before simulated initialization";
            [s record:@"SIMULATED Resume; startup gate passed"]; }
        event:^(NSString *state,NSError *error){
            RRLabViewController *s=weakSelf;if (!s) return;
            s->_busy=[state isEqual:@"restoring"];
            if ([state isEqual:@"ready"]) s->_ready=YES;
            if (s->_busy) [s->_spinner startAnimating];else [s->_spinner stopAnimating];
            s->_status.text=error ? [@"Failed — retry available: " stringByAppendingString:error.localizedDescription]
                : ([state isEqual:@"ready"] ? @"Resources verified; simulated startup waits for active scene" : @"Restoring local resources…");
            [s record:error ? [NSString stringWithFormat:@"%@ (%ld)",state,(long)error.code] : state];
        }];
    [_gate setActive:_active];
}
- (void)run { if (_gate) [_gate start]; }
- (void)cancel { [_gate cancel]; }
- (void)setLabActive:(BOOL)active { _active=active;[_gate setActive:active]; }
- (void)simulateActivation { [_gate setActive:NO];[_gate setActive:YES];[self record:@"Simulated inactive/active callbacks queued"]; }
- (void)changeTestResource:(BOOL)corrupt {
    if (_busy || !_ready) return;
    NSString *path=[[_container stringByAppendingPathComponent:@"Library/Caches"] stringByAppendingPathComponent:_manifest[0][@"path"]];
    NSError *error=nil;
    if (corrupt) [@"CORRUPTED LAB COPY\n" writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:&error];
    else [NSFileManager.defaultManager removeItemAtPath:path error:&error];
    if (error) { [self record:@"Could not change isolated test resource"];return; }
    [self record:corrupt ? @"Corrupted one isolated restored file" : @"Removed one isolated restored file"];
    [self makeGate];[self run];
}
- (void)testMissing { [self changeTestResource:NO]; }
- (void)testCorrupt { [self changeTestResource:YES]; }
@end

@interface RRLabSceneDelegate : UIResponder <UIWindowSceneDelegate>
@property(nonatomic,strong) UIWindow *window;
@property(nonatomic,strong) RRLabViewController *lab;
@end
@implementation RRLabSceneDelegate
- (void)scene:(UIScene *)scene willConnectToSession:(UISceneSession *)session options:(UISceneConnectionOptions *)options {
    (void)session;(void)options;
    if (![scene isKindOfClass:UIWindowScene.class]) return;
    self.window=[[UIWindow alloc] initWithWindowScene:(UIWindowScene *)scene];
    self.lab=[RRLabViewController new];
    self.window.rootViewController=[[UINavigationController alloc] initWithRootViewController:self.lab];
    [self.window makeKeyAndVisible];
}
- (void)sceneDidBecomeActive:(UIScene *)scene { (void)scene;[self.lab setLabActive:YES]; }
- (void)sceneWillResignActive:(UIScene *)scene { (void)scene;[self.lab setLabActive:NO]; }
@end
@interface RRLabAppDelegate : UIResponder <UIApplicationDelegate>
@end
@implementation RRLabAppDelegate
- (UISceneConfiguration *)application:(UIApplication *)app configurationForConnectingSceneSession:(UISceneSession *)session options:(UISceneConnectionOptions *)options {
    (void)app;(void)options;
    UISceneConfiguration *configuration=[[UISceneConfiguration alloc] initWithName:@"Resource Lab" sessionRole:session.role];
    configuration.delegateClass=RRLabSceneDelegate.class;
    return configuration;
}
@end
int main(int argc,char **argv) {
    @autoreleasepool { return UIApplicationMain(argc,argv,nil,NSStringFromClass(RRLabAppDelegate.class)); }
}
