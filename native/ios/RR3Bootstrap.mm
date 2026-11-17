// Experimental pre-nib gate. RR3's methods, nibs and construction flags remain
// unchanged. The packager redirects only RR3's UIApplicationMain import here.
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import "RRResourceRuntime.h"
#include <dlfcn.h>

// Renaming RR3 invalidates its hardcoded Firebase region selector. Preserve the
// existing regional options without changing the app identity or game methods.
static NSString *RR3FirebaseFallbackFile;
@interface NSObject (RR3FirebaseInitAlias)
- (instancetype)rr3_preservedFirebaseInitWithContentsOfFile:(NSString *)path
    __attribute__((objc_method_family(init)));
@end
@interface RR3FirebaseOptionsShim : NSObject
- (instancetype)rr3_checkedFirebaseInitWithContentsOfFile:(NSString *)path
    __attribute__((objc_method_family(init)));
@end
@implementation RR3FirebaseOptionsShim
- (instancetype)rr3_checkedFirebaseInitWithContentsOfFile:(NSString *)path {
    NSDictionary *options=[NSDictionary dictionaryWithContentsOfFile:path];
    if (RR3FirebaseFallbackFile && ![options[@"GOOGLE_APP_ID"] isKindOfClass:NSString.class]
        && [path hasPrefix:[NSBundle.mainBundle.resourcePath stringByAppendingString:@"/"]]) {
        NSLog(@"RR3 restoration: redirecting invalid Firebase options to preserved regional config");
        path=RR3FirebaseFallbackFile;
    }
    return [self rr3_preservedFirebaseInitWithContentsOfFile:path];
}
@end
static void RR3PrepareFirebaseCompatibility(void) {
    NSString *name=NSBundle.mainBundle.infoDictionary[@"RR3FirebaseConfigResource"];
    if (![name isKindOfClass:NSString.class]) return;
    NSString *path=[NSBundle.mainBundle pathForResource:name ofType:@"plist"];
    NSDictionary *options=path ? [NSDictionary dictionaryWithContentsOfFile:path] : nil;
    if (![options[@"GOOGLE_APP_ID"] isKindOfClass:NSString.class]) return;
    Class cls=NSClassFromString(@"FIROptions");
    SEL selector=@selector(initWithContentsOfFile:);
    SEL alias=@selector(rr3_preservedFirebaseInitWithContentsOfFile:);
    Method original=class_getInstanceMethod(cls,selector);
    Method shim=class_getInstanceMethod(RR3FirebaseOptionsShim.class,@selector(rr3_checkedFirebaseInitWithContentsOfFile:));
    if (!cls || !original || !shim || method_getNumberOfArguments(original)!=3) return;
    if (class_addMethod(cls,alias,method_getImplementation(original),method_getTypeEncoding(original))) {
        RR3FirebaseFallbackFile=path;
        class_replaceMethod(cls,selector,method_getImplementation(shim),method_getTypeEncoding(original));
    }
}

@interface RR3BootstrapDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic,strong) UIWindow *window;
@property(nonatomic,strong) RRResourceGate *gate;
@property(nonatomic,strong) UIApplication *application;
@property(nonatomic,strong) NSDictionary *options;
@property(nonatomic,strong) NSArray *originalObjects;
@property(nonatomic,strong) id<UIApplicationDelegate> originalDelegate;
@property(nonatomic,strong) NSMutableArray *events;
@property(nonatomic,strong) UILabel *status;
@property(nonatomic,strong) NSString *evidence;
@property(nonatomic) BOOL failedHandoff;
@property(nonatomic) BOOL nibAttempted;
- (void)record:(NSString *)event;
@end

// UIApplication.delegate is not an ownership root. Retain the bootstrap and nib
// top-level objects for the process lifetime, including after delegate handoff.
static RR3BootstrapDelegate *RRBootstrapLifetime;

@implementation RR3BootstrapDelegate
- (void)record:(NSString *)event {
    NSAssert(NSThread.isMainThread, @"Bootstrap events must run on main");
    [self.events addObject:@{@"event":event,@"time":@([NSDate timeIntervalSinceReferenceDate])}];
    NSDictionary *result=@{@"build":NSBundle.mainBundle.infoDictionary[@"RR3InitializerBuild"] ?: @"unknown",
        @"scope":@"RR3 pre-nib resource initialization",
        @"os":UIDevice.currentDevice.systemVersion,@"events":self.events};
    NSData *data=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:nil];
    [data writeToFile:self.evidence atomically:YES];
}
- (void)handoffFailure:(NSString *)message {
    self.application.idleTimerDisabled=NO;
    self.failedHandoff=YES;
    self.application.delegate=self;
    self.window.hidden=NO;[self.window makeKeyWindow];
    self.status.text=[@"Startup held: " stringByAppendingString:message];
    [self record:message];
}
- (void)loadOriginalNib {
    self.nibAttempted=YES;
    [self record:@"original_nib_begin_after_verified_seed"];
    @try {
        NSDictionary *info=NSBundle.mainBundle.infoDictionary;
        NSString *nib=UIDevice.currentDevice.userInterfaceIdiom==UIUserInterfaceIdiomPad
            ? (info[@"RR3OriginalMainNibIPad"] ?: info[@"RR3OriginalMainNib"])
            : info[@"RR3OriginalMainNib"];
        // The preserved nib's IBFilesOwner.delegate outlet points to its
        // RealRacingAppDelegate. Owner must therefore be the UIApplication.
        self.originalObjects=[NSBundle.mainBundle loadNibNamed:nib owner:self.application options:nil];
        id<UIApplicationDelegate> delegate=self.application.delegate;
        if (!self.originalObjects.count || ![(id)delegate isKindOfClass:NSClassFromString(@"RealRacingAppDelegate")]) {
            [self handoffFailure:@"Original nib/delegate wiring failed; restart required"];return;
        }
        self.originalDelegate=delegate;
        [self record:@"original_nib_end_delegate_verified"];
    } @catch (NSException *) {
        [self handoffFailure:@"Original nib raised an exception; restart required"];
    }
}
- (void)launchOriginal {
    if (self.failedHandoff) return;
    RR3PrepareFirebaseCompatibility();
    [self record:@"original_didFinish_begin"];
    @try {
        // Invoke the complete preserved method once, not individual constructors.
        BOOL ok=[self.originalDelegate application:self.application didFinishLaunchingWithOptions:self.options];
        if (!ok) {[self handoffFailure:@"Original launch returned NO; restart required"];return;}
        [self record:@"original_didFinish_end"];
    } @catch (NSException *exception) {
        [self handoffFailure:[NSString stringWithFormat:@"Original launch exception %@: %@; restart required",
            exception.name,exception.reason ?: @"no reason provided"]];
    }
}
- (void)activateOriginal {
    if (self.failedHandoff) return;
    self.application.idleTimerDisabled=NO;
    self.window.hidden=YES;
    [self record:@"original_didBecomeActive_begin"];
    if ([self.originalDelegate respondsToSelector:@selector(applicationDidBecomeActive:)])
        [self.originalDelegate applicationDidBecomeActive:self.application];
    [self record:@"handoff_complete_future_callbacks_use_original_delegate"];
}
- (void)retry {
    // Nib/engine construction is not reversible in-process. Retry only seed work.
    if (!self.nibAttempted) [self.gate start];
}
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    RRBootstrapLifetime=self;
    self.application=application;self.options=options;self.events=[NSMutableArray array];
    application.idleTimerDisabled=YES;
    NSURL *support=[NSFileManager.defaultManager URLForDirectory:NSApplicationSupportDirectory
        inDomain:NSUserDomainMask appropriateForURL:nil create:YES error:nil];
    NSString *root=[support.path stringByAppendingPathComponent:@"RR3Restored/ResourceInitialization"];
    [NSFileManager.defaultManager createDirectoryAtPath:root withIntermediateDirectories:YES attributes:nil error:nil];
    self.evidence=[root stringByAppendingPathComponent:@"startup-trace.json"];
    self.window=[[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *controller=[UIViewController new];
    controller.view.backgroundColor=UIColor.systemBackgroundColor;
    self.status=[UILabel new];self.status.numberOfLines=0;self.status.text=@"RR3 Restored: verifying local test resources…";
    UIButton *retry=[UIButton buttonWithType:UIButtonTypeSystem];
    [retry setTitle:@"Retry resource preparation" forState:UIControlStateNormal];
    [retry addTarget:self action:@selector(retry) forControlEvents:UIControlEventTouchUpInside];
    UIStackView *stack=[[UIStackView alloc] initWithArrangedSubviews:@[self.status,retry]];
    stack.axis=UILayoutConstraintAxisVertical;stack.spacing=20;stack.translatesAutoresizingMaskIntoConstraints=NO;
    [controller.view addSubview:stack];
    [NSLayoutConstraint activateConstraints:@[
        [stack.leadingAnchor constraintEqualToAnchor:controller.view.safeAreaLayoutGuide.leadingAnchor constant:24],
        [stack.trailingAnchor constraintEqualToAnchor:controller.view.safeAreaLayoutGuide.trailingAnchor constant:-24],
        [stack.centerYAnchor constraintEqualToAnchor:controller.view.centerYAnchor]]];
    self.window.rootViewController=controller;[self.window makeKeyAndVisible];
    [self record:@"bootstrap_didFinish_no_game_nib_loaded"];
    NSString *seed=[NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"RR3ResourceSeed"];
    NSData *data=[NSData dataWithContentsOfFile:[NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"rr3-seed-manifest.json"]];
    NSArray *manifest=data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    if (![manifest isKindOfClass:NSArray.class] || !manifest.count) {
        [self handoffFailure:@"Resource seed manifest missing"];return YES;
    }
    __weak RR3BootstrapDelegate *weak=self;
    self.gate=[[RRResourceGate alloc] initWithQueue:dispatch_get_main_queue()
        work:^NSError *(RRStopCheck stop){
            NSError *error=nil;
            NSDictionary *result=RRRestoreExperimentalSeed(seed,manifest,stop,&error);
            return result ? nil : (error ?: [NSError errorWithDomain:@"RR3Bootstrap" code:1
                userInfo:@{NSLocalizedDescriptionKey:@"Resource preparation failed"}]);
        } timeout:[NSBundle.mainBundle.infoDictionary[@"RR3InitializerMode"] isEqual:@"full-pre-nib-v1"] ? 3600 : 30
        partOne:^{[weak loadOriginalNib];}
        partTwo:^{[weak launchOriginal];} resume:^{[weak activateOriginal];}
        event:^(NSString *state,NSError *error){
            RR3BootstrapDelegate *s=weak;
            s.status.text=error ? [@"Resource preparation failed: " stringByAppendingString:error.localizedDescription]
                : [@"RR3 Restored: " stringByAppendingString:state];
            if (error) s.application.idleTimerDisabled=NO;
            [s record:error ? [NSString stringWithFormat:@"seed_%@_%ld",state,(long)error.code]
                             : [@"seed_" stringByAppendingString:state]];
        }];
    [self.gate setActive:application.applicationState==UIApplicationStateActive];
    [self.gate start];
    return YES;
}
- (void)applicationDidBecomeActive:(UIApplication *)application {
    (void)application;[self record:@"bootstrap_active"];[self.gate setActive:YES];
}
- (void)applicationWillResignActive:(UIApplication *)application {
    (void)application;[self record:@"bootstrap_inactive"];[self.gate setActive:NO];
}
- (void)applicationDidEnterBackground:(UIApplication *)application {
    (void)application;[self.gate setActive:NO];
}
@end

// Same import name, different two-level library ordinal in the isolated game.
// UIKit's own implementation is resolved from its explicit framework handle.
extern "C" __attribute__((visibility("default"))) int UIApplicationMain(
        int argc,char **argv,NSString *principal,NSString *delegate) {
    @autoreleasepool {
        NSDictionary *info=NSBundle.mainBundle.infoDictionary;
        if (principal || delegate || ![@[@"three-file-pre-nib-v1", @"full-pre-nib-v1"] containsObject:info[@"RR3InitializerMode"]]
            || info[@"NSMainNibFile"] || info[@"NSMainNibFile~ipad"]
            || ![NSBundle.mainBundle.bundleIdentifier hasPrefix:@"org.rr3preservation.restored"])
            __builtin_trap(); // Refuse an unreviewed entry or accidental original-app use.
        void *handle=dlopen("/System/Library/Frameworks/UIKit.framework/UIKit",RTLD_NOW|RTLD_LOCAL);
        using Entry=int (*)(int,char **,NSString *,NSString *);
        Entry original=handle ? reinterpret_cast<Entry>(dlsym(handle,"UIApplicationMain")) : nullptr;
        if (!original || original==&UIApplicationMain) __builtin_trap();
        return original(argc,argv,nil,NSStringFromClass(RR3BootstrapDelegate.class));
    }
}
