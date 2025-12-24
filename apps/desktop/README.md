1. 前置环境要求
Node.js: 建议版本 v18.x 或更高 (推荐 LTS 版本)。
包管理器: 推荐使用 pnpm (磁盘占用更小，速度更快)。
```
# 如果未安装 pnpm
npm install -g pnpm
```

2. 项目初始化 (若是新建)
如果是从零创建项目，执行以下命令：
```
pnpm create electron-vite desktop
# 选项推荐：
pnpm create electron-vite desktop
# 选项推荐：

# > Framework: Vue
# > TypeScript: Yes
# > Electron Updater: No (MVP阶段可选No)
```
3. 安装依赖
在项目根目录下执行：
```
pnpm install
```
4. 启动开发环境
```
pnpm run dev
```