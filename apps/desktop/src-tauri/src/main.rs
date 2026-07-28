// 桌面纯壳入口：仅承载 Web 构建产物，算力全在云端（CLOUD_FIRST）
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use sha2::{Digest, Sha256};

/// 机器码哈希盐（docs/19：与前端指纹协议约定，勿改）
const MACHINE_CODE_SALT: &str = "oral-ip-device-v1";

/// 读取各平台稳定机器码原始值（清缓存/重装应用不变）
fn raw_machine_id() -> Result<String, String> {
    #[cfg(target_os = "macos")]
    {
        // IOPlatformUUID：主板级唯一标识
        let output = std::process::Command::new("ioreg")
            .args(["-rd1", "-c", "IOPlatformExpertDevice"])
            .output()
            .map_err(|e| format!("ioreg failed: {e}"))?;
        let text = String::from_utf8_lossy(&output.stdout);
        for line in text.lines() {
            if line.contains("IOPlatformUUID") {
                if let Some(value) = line.split('"').nth(3) {
                    return Ok(value.trim().to_string());
                }
            }
        }
        Err("IOPlatformUUID not found".to_string())
    }
    #[cfg(target_os = "windows")]
    {
        // MachineGuid：系统安装期生成，注册表持久
        let output = std::process::Command::new("reg")
            .args([
                "query",
                r"HKLM\SOFTWARE\Microsoft\Cryptography",
                "/v",
                "MachineGuid",
            ])
            .output()
            .map_err(|e| format!("reg query failed: {e}"))?;
        let text = String::from_utf8_lossy(&output.stdout);
        for line in text.lines() {
            if line.contains("MachineGuid") {
                if let Some(value) = line.split_whitespace().last() {
                    return Ok(value.trim().to_string());
                }
            }
        }
        Err("MachineGuid not found".to_string())
    }
    #[cfg(target_os = "linux")]
    {
        std::fs::read_to_string("/etc/machine-id")
            .map(|s| s.trim().to_string())
            .map_err(|e| format!("read machine-id failed: {e}"))
    }
}

/// 硬件机器码指纹设备段：hw-{SHA256(机器码+盐) 前 32 位 hex}
/// 任一步失败返回 Err，前端降级 localStorage UUID（docs/19 §2.6）
#[tauri::command]
fn machine_code() -> Result<String, String> {
    let raw = raw_machine_id()?;
    if raw.is_empty() {
        return Err("machine id empty".to_string());
    }
    let digest = Sha256::digest(format!("{raw}{MACHINE_CODE_SALT}").as_bytes());
    let hex: String = digest.iter().map(|b| format!("{b:02x}")).collect();
    Ok(format!("hw-{}", &hex[..32]))
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![machine_code])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
