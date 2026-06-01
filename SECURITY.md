# 安全策略 / Security Policy

## 声纹数据保护声明

声纹数据（Voiceprint Embedding）属 **敏感个人生物信息**。

### 强制规定
- ✅ 所有声纹训练数据（embedding、profile、音频样本）**仅存储在本地** `dict/voiceprints/` 目录
- ❌ **严禁**将任何声纹数据文件上传至 GitHub、Gitee 或任何远程代码仓库
- 🛡 `dict/voiceprints/` 目录已被 `.gitignore` 永久排除
- 🛡 `*.npy`、`*.bin`、`*.pkl` 等声纹embedding格式已被 `.gitignore` 永久排除

### 数据安全层级
1. **本地存储**：声纹数据仅存在于用户本机
2. **Git 过滤**：所有声纹相关目录和文件格式已加入 .gitignore
3. **路径校验**：系统运行时强制校验声纹数据写入路径，拒绝非本地写入

### 违规后果
任何将声纹数据上传至公共仓库的行为均构成 **生物信息泄露**，可能违反：
- 《中华人民共和国个人信息保护法》
- 《中华人民共和国数据安全法》
- GDPR (EU General Data Protection Regulation)