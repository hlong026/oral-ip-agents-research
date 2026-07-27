// 桌面纯壳入口：仅承载 Web 构建产物，算力全在云端（CLOUD_FIRST）
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
