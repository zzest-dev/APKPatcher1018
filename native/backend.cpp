#include <jni.h>
#include <android/log.h>
#include <dlfcn.h>
#include <dobby.h>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>



using Method = const void;
using Object = void;
using Class = void;
struct Api {
    void *(*domain_get)();
    const void **(*domain_get_assemblies)(void *, size_t *);
    const void *(*assembly_get_image)(const void *);
    Class *(*class_from_name)(const void *, const char *, const char *);
    Method *(*class_get_method_from_name)(Class *, const char *, int);
    Method *(*class_get_methods)(Class *, void **);
    const char *(*method_get_name)(Method *);
    uint32_t (*method_get_param_count)(Method *);
    const void *(*method_get_param)(Method *, uint32_t);
    char *(*type_get_name)(const void *);
    void (*free)(void *);
    Object *(*object_new)(Class *);
    Object *(*string_new)(const char *);
    const uint16_t *(*string_chars)(Object *);
    int32_t (*string_length)(Object *);
    Object *(*runtime_invoke)(Method *, Object *, void **, Object **);
    void *(*thread_current)();
    uint32_t (*gchandle_new)(Object *, bool);
    void (*gchandle_free)(uint32_t);
    Object *(*gchandle_get_target)(uint32_t);
    void *(*class_get_field_from_name)(Class *, const char *);
    void (*field_static_get_value)(void *, void *);
    void (*field_get_value)(Object *, void *, void *);
    Class *(*object_get_class)(Object *);
    Object *(*array_new)(Class *, uintptr_t);
    uintptr_t (*array_length)(Object *);
    void (*gc_wbarrier_set_field)(Object *, void **, void *);
    void (*field_static_set_value)(void *, void *);
    void (*field_set_value)(Object *, void *, void *);
} api{};
static bool ready = false;
static uint32_t endpointHandle, hostHandle;
static int configuredPort;
static Method *linkMethod;
using LinkFn = Object *(*)(Object *, Object *, int, bool, Method *);
using RequestFn = void (*)(Object *, Object *, Object *, Object *, float, int, Method *);
using UpdateFn = void (*)(Object *, Method *);
static LinkFn originalLink;
static RequestFn originalRequest;
static UpdateFn originalUpdate, originalLoad;

static Class *FindClass(const char *space, const char *name) {
    size_t count = 0;
    auto assemblies = api.domain_get_assemblies(api.domain_get(), &count);
    for (size_t i = 0; i < count; ++i) {
        auto cls = api.class_from_name(api.assembly_get_image(assemblies[i]), space, name);
        if (cls) return cls;
    }
    return nullptr;
}
static Object *Invoke(Method *method, Object *self, void **args, bool &ok) {
    Object *exception = nullptr;
    auto result = api.runtime_invoke(method, self, args, &exception);
    ok = exception == nullptr;
    if (!ok) {
        auto cls = api.object_get_class(exception);
        auto toString = cls ? api.class_get_method_from_name(cls, "ToString", 0) : nullptr;
        Object *nested = nullptr;
        auto message = toString ? api.runtime_invoke(toString, exception, nullptr, &nested) : nullptr;
        std::string text;
        if (message && !nested) {
            auto chars = api.string_chars(message);
            for (int i = 0; i < api.string_length(message) && i < 1600; ++i) text += chars[i] < 128 ? char(chars[i]) : '?';
        }
        __android_log_print(ANDROID_LOG_ERROR, "Backend1018", "Managed call failed: %s", text.c_str());
    }
    return result;
}
static Object *GetLink(Object *self, Object *, int, bool, Method *method) {
    return originalLink(self, api.gchandle_get_target(hostHandle), configuredPort, false, method);
}
static void Request(Object *self, Object *channel, Object *, Object *url, float timeout, int, Method *method) {
    std::string route;
    if (url) {
        auto chars = api.string_chars(url);
        int count = api.string_length(url);
        for (int i = 0; i < count && i < 120; ++i) route += chars[i] >= 32 && chars[i] < 127 ? static_cast<char>(chars[i]) : '?';
    }
    static std::string lastRoute;
    if (route != lastRoute) {
        __android_log_print(ANDROID_LOG_INFO, "Backend1018", "Request %s", route.c_str());
        lastRoute = route;
    }
    originalRequest(self, channel, api.gchandle_get_target(endpointHandle), url, timeout, 1, method);
}
static void Update(Object *self, Method *method) {
    GetLink(self, nullptr, 0, false, linkMethod);
    originalUpdate(self, method);
}
static void LoadFromSite(Object *, Method *) {}
struct Hook {
    Method *method;
    uintptr_t rva;
    void *replacement;
    void **original;
};
extern "C" JNIEXPORT jint JNICALL Java_com_bigcitylegacy_backend_BackendActivity_nativeInitialize(JNIEnv *env, jclass, jstring ip, jint port) {
    if (ready) return 1;
    static void *library = nullptr;
    if (!library) library = dlopen("libil2cpp.so", RTLD_NOW | RTLD_NOLOAD);
    if (!library) return 0;
#define LOAD(name) api.name = reinterpret_cast<decltype(api.name)>(dlsym(library, "il2cpp_" #name)); if (!api.name) return -1
    LOAD(domain_get); LOAD(domain_get_assemblies); LOAD(assembly_get_image); LOAD(class_from_name);
    LOAD(class_get_method_from_name); LOAD(class_get_methods); LOAD(method_get_name); LOAD(method_get_param_count);
    LOAD(method_get_param); LOAD(type_get_name); LOAD(free); LOAD(object_new); LOAD(string_new);
    LOAD(string_chars); LOAD(string_length); LOAD(runtime_invoke); LOAD(thread_current);
    LOAD(gchandle_new); LOAD(gchandle_free); LOAD(gchandle_get_target);
    LOAD(class_get_field_from_name); LOAD(field_static_get_value);
    LOAD(field_get_value); LOAD(object_get_class);
    LOAD(array_new); LOAD(array_length); LOAD(gc_wbarrier_set_field);
    LOAD(field_static_set_value); LOAD(field_set_value);
#undef LOAD
    if (!api.domain_get() || !api.thread_current()) return 0;
    auto finder = FindClass("", "Client_FindMirror");
    auto req = FindClass("", "MyReq");
    auto addressClass = FindClass("System.Net", "IPAddress");
    auto endpointClass = FindClass("System.Net", "IPEndPoint");
    if (!finder || !req || !addressClass || !endpointClass) return 0;
    linkMethod = api.class_get_method_from_name(finder, "GetOrCreateLink", 3);
    Hook hooks[] = {
        {linkMethod, 0x6D58A0, reinterpret_cast<void *>(GetLink), reinterpret_cast<void **>(&originalLink)},
        {api.class_get_method_from_name(req, ".ctor", 5), 0xA03100, reinterpret_cast<void *>(Request), reinterpret_cast<void **>(&originalRequest)},
        {api.class_get_method_from_name(finder, "Update", 0), 0x6D61E4, reinterpret_cast<void *>(Update), reinterpret_cast<void **>(&originalUpdate)},
        {api.class_get_method_from_name(finder, "LoadFromSite", 0), 0x6D68B4, reinterpret_cast<void *>(LoadFromSite), reinterpret_cast<void **>(&originalLoad)}
    };
    Dl_info info{};
    if (!dladdr(reinterpret_cast<void *>(api.domain_get), &info)) return -2;
    auto base = reinterpret_cast<uintptr_t>(info.dli_fbase);
    for (auto &hook : hooks) {
        if (!hook.method || *static_cast<const uintptr_t *>(hook.method) != base + hook.rva) {
            __android_log_print(ANDROID_LOG_ERROR, "Backend1018", "Unsupported method layout at %x", static_cast<unsigned>(hook.rva));
            return -3;
        }
    }
    auto parse = api.class_get_method_from_name(addressClass, "Parse", 1);
    Method *ctor = nullptr;
    void *iterator = nullptr;
    while (auto method = api.class_get_methods(endpointClass, &iterator)) {
        if (std::strcmp(api.method_get_name(method), ".ctor") || api.method_get_param_count(method) != 2) continue;
        auto type = api.type_get_name(api.method_get_param(method, 0));
        bool match = type && std::strcmp(type, "System.Net.IPAddress") == 0;
        api.free(type);
        if (match) { ctor = method; break; }
    }
    if (!parse || !ctor) return -4;
    const char *host = env->GetStringUTFChars(ip, nullptr);
    auto hostObject = api.string_new(host);
    env->ReleaseStringUTFChars(ip, host);
    hostHandle = api.gchandle_new(hostObject, false);
    bool ok = false;
    void *parseArgs[] = {hostObject};
    auto address = Invoke(parse, nullptr, parseArgs, ok);
    if (!ok || !address) { api.gchandle_free(hostHandle); return -5; }
    auto endpoint = api.object_new(endpointClass);
    configuredPort = port;
    void *ctorArgs[] = {address, &configuredPort};
    Invoke(ctor, endpoint, ctorArgs, ok);
    if (!ok) { api.gchandle_free(hostHandle); return -6; }
    endpointHandle = api.gchandle_new(endpoint, false);
    std::vector<void *> installed;
    for (auto &hook : hooks) {
        auto target = reinterpret_cast<void *>(base + hook.rva);
        if (DobbyHook(target, reinterpret_cast<dobby_dummy_func_t>(hook.replacement), reinterpret_cast<dobby_dummy_func_t *>(hook.original)) != 0) {
            for (auto at = installed.rbegin(); at != installed.rend(); ++at) DobbyDestroy(*at);
            api.gchandle_free(hostHandle);
            api.gchandle_free(endpointHandle);
            return -7;
        }
        installed.push_back(target);
    }
    ready = true;
    __android_log_print(ANDROID_LOG_INFO, "Backend1018", "Hooks installed for verified ARMv7 10.18");
    return 1;
}
