# 保留 WebView JavaScript 接口
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}

# 保留 WebView 相关类
-keep public class android.webkit.** { *; }
-dontwarn android.webkit.**