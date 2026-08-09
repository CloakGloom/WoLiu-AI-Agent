package com.agent.app

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.view.KeyEvent
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.webkit.*
import android.widget.ProgressBar
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import java.io.File
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.*

/**
 * 主界面：WebView 加载移动端页面
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var progressBar: ProgressBar
    private var serverIp = "192.168.1.100"
    private var serverPort = "5000"
    private var baseUrl = ""

    // WebView 文件选择器（摄像头/相册）
    private var filePathCallback: ValueCallback<Array<Uri>>? = null
    private var cameraPhotoUri: Uri? = null

    // 摄像头权限请求
    private val cameraPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            openCameraChooser()
        } else {
            Toast.makeText(this, "需要摄像头权限才能拍照", Toast.LENGTH_SHORT).show()
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // 让内容延伸到系统栏下方，但手动处理 insets 避免被遮挡
        WindowCompat.setDecorFitsSystemWindows(window, false)
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.webView)) { view, insets ->
            val navBar = insets.getInsets(WindowInsetsCompat.Type.navigationBars())
            val statusBar = insets.getInsets(WindowInsetsCompat.Type.statusBars())
            view.setPadding(statusBar.left, statusBar.top, statusBar.right, navBar.bottom)
            insets
        }

        serverIp = intent.getStringExtra("server_ip") ?: "192.168.1.100"
        serverPort = intent.getStringExtra("server_port") ?: "5000"
        baseUrl = "http://${serverIp}:${serverPort}/mobile"

        webView = findViewById(R.id.webView)
        progressBar = findViewById(R.id.progressBar)

        setupWebView()
        loadPage()
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        val settings = webView.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.allowFileAccess = false
        settings.allowContentAccess = false
        settings.mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
        settings.cacheMode = WebSettings.LOAD_DEFAULT
        settings.setSupportZoom(false)
        settings.builtInZoomControls = false
        settings.displayZoomControls = false
        settings.loadWithOverviewMode = true
        settings.useWideViewPort = true
        // WebSocket 支持（Android 4.4+ 内置）
        settings.mediaPlaybackRequiresUserGesture = false

        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                progressBar.visibility = View.VISIBLE
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                progressBar.visibility = View.GONE
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?
            ) {
                progressBar.visibility = View.GONE
                if (request?.isForMainFrame == true) {
                    showErrorPage()
                }
            }

            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                // 拦截外部链接，用浏览器打开
                val url = request?.url?.toString() ?: return false
                if (url.startsWith("http://") || url.startsWith("https://")) {
                    if (url.startsWith(baseUrl)) {
                        return false // 内部链接在 WebView 中打开
                    }
                    // 外部链接用浏览器打开
                    val intent = Intent(Intent.ACTION_VIEW, android.net.Uri.parse(url))
                    startActivity(intent)
                    return true
                }
                return false
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                progressBar.progress = newProgress
            }

            // 处理文件选择器（摄像头/相册/文件）
            override fun onShowFileChooser(
                webView: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?
            ): Boolean {
                this@MainActivity.filePathCallback?.onReceiveValue(null)
                this@MainActivity.filePathCallback = filePathCallback

                // 检查是否只需要拍照（capture="environment"）
                val acceptTypes = fileChooserParams?.acceptTypes ?: arrayOf("*/*")
                val isCaptureImage = fileChooserParams?.isCaptureEnabled == true &&
                        acceptTypes.any { it.startsWith("image/") }

                if (isCaptureImage) {
                    // 拍照模式：先检查权限
                    if (ContextCompat.checkSelfPermission(this@MainActivity, android.Manifest.permission.CAMERA)
                        == PackageManager.PERMISSION_GRANTED) {
                        openCameraChooser()
                    } else {
                        cameraPermissionLauncher.launch(android.Manifest.permission.CAMERA)
                    }
                } else {
                    // 文件选择模式
                    val intent = Intent(Intent.ACTION_GET_CONTENT)
                    intent.addCategory(Intent.CATEGORY_OPENABLE)
                    intent.type = "*/*"
                    val chooserIntent = Intent(Intent.ACTION_CHOOSER)
                    chooserIntent.putExtra(Intent.EXTRA_INTENT, intent)
                    chooserIntent.putExtra(Intent.EXTRA_TITLE, "选择文件")

                    // 添加拍照选项
                    val cameraIntent = createCameraIntent()
                    if (cameraIntent != null) {
                        chooserIntent.putExtra(Intent.EXTRA_INITIAL_INTENTS, arrayOf(cameraIntent))
                    }

                    startActivityForResult(chooserIntent, FILE_CHOOSER_REQUEST)
                }
                return true
            }
        }
    }

    private fun loadPage() {
        if (!isNetworkAvailable()) {
            Toast.makeText(this, "网络不可用，请检查连接", Toast.LENGTH_LONG).show()
            progressBar.visibility = View.GONE
            return
        }
        webView.loadUrl(baseUrl)
    }

    private fun showErrorPage() {
        val errorHtml = """
            <html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
            <style>body{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;margin:0;font-family:sans-serif;background:#f5f6fa;color:#2c3e50;}
            .icon{font-size:64px;margin-bottom:16px;}h2{font-size:18px;margin-bottom:8px;}p{font-size:14px;color:#7f8c8d;text-align:center;padding:0 24px;}
            button{margin-top:20px;padding:12px 32px;background:#4a90d9;color:#fff;border:none;border-radius:8px;font-size:14px;cursor:pointer;}
            </style></head><body>
            <div class="icon">🔌</div>
            <h2>无法连接到服务器</h2>
            <p>请确认电脑端 Agent 服务已启动<br>地址：${serverIp}:${serverPort}</p>
            <button onclick="location.reload()">重试</button>
            </body></html>
        """.trimIndent()
        webView.loadDataWithBaseURL(null, errorHtml, "text/html", "UTF-8", null)
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BACK && webView.canGoBack()) {
            webView.goBack()
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    override fun onCreateOptionsMenu(menu: Menu?): Boolean {
        menuInflater.inflate(R.menu.main_menu, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        return when (item.itemId) {
            R.id.action_refresh -> {
                loadPage()
                true
            }
            R.id.action_settings -> {
                // 返回设置页
                val intent = Intent(this, SetupActivity::class.java)
                intent.flags = Intent.FLAG_ACTIVITY_CLEAR_TOP
                startActivity(intent)
                finish()
                true
            }
            R.id.action_clear -> {
                AlertDialog.Builder(this)
                    .setTitle("清空聊天记录")
                    .setMessage("确定要清空当前会话的所有聊天记录吗？")
                    .setPositiveButton("确定") { _, _ ->
                        webView.evaluateJavascript(
                            "fetch('/api/sessions/current/messages',{method:'DELETE'})", null
                        )
                        webView.reload()
                    }
                    .setNegativeButton("取消", null)
                    .show()
                true
            }
            else -> super.onOptionsItemSelected(item)
        }
    }

    private fun isNetworkAvailable(): Boolean {
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val network = cm.activeNetwork ?: return false
        val capabilities = cm.getNetworkCapabilities(network) ?: return false
        return capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    override fun onDestroy() {
        webView.destroy()
        super.onDestroy()
    }

    // ===== 摄像头/文件选择器 =====

    private fun createCameraIntent(): Intent? {
        return try {
            val photoFile = createImageFile()
            cameraPhotoUri = FileProvider.getUriForFile(
                this,
                "${packageName}.fileprovider",
                photoFile
            )
            Intent(MediaStore.ACTION_IMAGE_CAPTURE).apply {
                putExtra(MediaStore.EXTRA_OUTPUT, cameraPhotoUri)
            }
        } catch (e: IOException) {
            e.printStackTrace()
            null
        }
    }

    private fun openCameraChooser() {
        val intent = createCameraIntent()
        if (intent != null) {
            startActivityForResult(intent, CAMERA_REQUEST)
        } else {
            Toast.makeText(this, "无法启动摄像头", Toast.LENGTH_SHORT).show()
            filePathCallback?.onReceiveValue(null)
            filePathCallback = null
        }
    }

    @Throws(IOException::class)
    private fun createImageFile(): File {
        val timeStamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault()).format(Date())
        val imageDir = File(externalCacheDir, "camera")
        if (!imageDir.exists()) imageDir.mkdirs()
        return File.createTempFile("JPEG_${timeStamp}_", ".jpg", imageDir)
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)

        when (requestCode) {
            CAMERA_REQUEST -> {
                var results: Array<Uri>? = null
                if (resultCode == RESULT_OK) {
                    results = cameraPhotoUri?.let { arrayOf(it) }
                }
                filePathCallback?.onReceiveValue(results)
                filePathCallback = null
            }
            FILE_CHOOSER_REQUEST -> {
                if (resultCode == RESULT_OK && data?.data != null) {
                    filePathCallback?.onReceiveValue(arrayOf(data.data!!))
                } else {
                    filePathCallback?.onReceiveValue(null)
                }
                filePathCallback = null
            }
        }
    }

    companion object {
        private const val CAMERA_REQUEST = 1001
        private const val FILE_CHOOSER_REQUEST = 1002
    }
}