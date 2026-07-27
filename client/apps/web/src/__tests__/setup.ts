import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// globals:false 模式下 RTL 无法自动清理，手动注册
afterEach(cleanup);
