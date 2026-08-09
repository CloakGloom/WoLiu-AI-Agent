package com.agent.app

import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.widget.doOnTextChanged

/**
 * 启动页：输入 PC 服务器地址
 */
class SetupActivity : AppCompatActivity() {

    private lateinit var prefs: SharedPreferences
    private lateinit var ipInput: EditText
    private lateinit var portInput: EditText
    private lateinit var connectBtn: Button
    private lateinit var lastServerText: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_setup)

        prefs = getSharedPreferences("agent_prefs", Context.MODE_PRIVATE)

        ipInput = findViewById(R.id.ipInput)
        portInput = findViewById(R.id.portInput)
        connectBtn = findViewById(R.id.connectBtn)
        lastServerText = findViewById(R.id.lastServerText)

        // 恢复上次的地址
        val lastIp = prefs.getString("server_ip", "192.168.1.100")
        val lastPort = prefs.getString("server_port", "5000")
        ipInput.setText(lastIp)
        portInput.setText(lastPort)
        lastServerText.text = "上次连接：${lastIp}:${lastPort}"

        // 输入变化时更新按钮状态
        ipInput.doOnTextChanged { _, _, _, _ -> updateConnectButton() }
        portInput.doOnTextChanged { _, _, _, _ -> updateConnectButton() }

        connectBtn.setOnClickListener { connect() }
    }

    private fun updateConnectButton() {
        val ip = ipInput.text.toString().trim()
        val port = portInput.text.toString().trim()
        connectBtn.isEnabled = ip.isNotEmpty() && port.isNotEmpty()
    }

    private fun connect() {
        val ip = ipInput.text.toString().trim()
        val port = portInput.text.toString().trim()

        if (ip.isEmpty() || port.isEmpty()) {
            Toast.makeText(this, "请输入 IP 地址和端口", Toast.LENGTH_SHORT).show()
            return
        }

        // 保存地址
        prefs.edit().apply {
            putString("server_ip", ip)
            putString("server_port", port)
            apply()
        }

        // 跳转到主界面
        val intent = Intent(this, MainActivity::class.java).apply {
            putExtra("server_ip", ip)
            putExtra("server_port", port)
        }
        startActivity(intent)
    }
}