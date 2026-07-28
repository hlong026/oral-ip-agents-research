// 桌面纯壳入口：仅承载 Web 构建产物，算力全在云端（CLOUD_FIRST）
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs;
use std::path::PathBuf;

use sha2::{Digest, Sha256};
use tauri::Manager;

/// 机器码哈希盐（docs/19：与前端指纹协议约定，勿改）
const MACHINE_CODE_SALT: &str = "oral-ip-device-v1";

/// 持久化会话令牌文件名（存于应用数据目录，webview 清缓存/重装应用不丢）
const SESSION_TOKEN_FILE: &str = "session.token";

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

/// 会话令牌文件路径：应用数据目录下 session.token（目录不存在则创建）
fn session_token_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("app_data_dir failed: {e}"))?;
    fs::create_dir_all(&dir).map_err(|e| format!("create app data dir failed: {e}"))?;
    Ok(dir.join(SESSION_TOKEN_FILE))
}

/// 读取持久化 refresh token；无文件视为无会话（返回空串，非报错）
#[tauri::command]
fn session_token_read(app: tauri::AppHandle) -> Result<String, String> {
    let path = session_token_path(&app)?;
    match fs::read_to_string(&path) {
        Ok(token) => Ok(token.trim().to_string()),
        Err(_) => Ok(String::new()),
    }
}

/// 持久化 refresh token 到应用数据目录（登录/令牌轮换后调用）
#[tauri::command]
fn session_token_write(app: tauri::AppHandle, token: String) -> Result<(), String> {
    let path = session_token_path(&app)?;
    fs::write(&path, token.trim()).map_err(|e| format!("write session token failed: {e}"))?;
    // 收紧权限为 0600：refresh token 为长效凭证，避免同机其他用户可读
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600))
            .map_err(|e| format!("chmod session token failed: {e}"))?;
    }
    Ok(())
}

/// 清除持久化 token（登出/刷新失败）
#[tauri::command]
fn session_token_clear(app: tauri::AppHandle) -> Result<(), String> {
    let path = session_token_path(&app)?;
    if path.exists() {
        fs::remove_file(&path).map_err(|e| format!("clear session token failed: {e}"))?;
    }
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            machine_code,
            session_token_read,
            session_token_write,
            session_token_clear
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
