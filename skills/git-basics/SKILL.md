---
name: git-basics
description: Git 版本控制基础，涵盖日常开发、协作、分支管理等核心操作
---

# Git 版本控制基础

## 基础配置

```bash
# 设置用户名和邮箱
git config --global user.name "Your Name"
git config --global user.email "your@email.com"

# 查看配置
git config --list

# 设置默认编辑器
git config --global core.editor vim
```

## 日常工作流程

### 创建仓库
```bash
# 初始化新仓库
git init

# 克隆远程仓库
git clone <repository-url>
```

### 添加和提交
```bash
# 查看状态
git status

# 添加文件到暂存区
git add <file>           # 添加单个文件
git add .                # 添加所有改动
git add -A               # 添加所有（包括删除的文件）

# 提交改动
git commit -m "提交信息"
git commit -am "提交信息"  # 跳过 add，直接提交已追踪文件

# 修改最后一次提交
git commit --amend
```

### 查看历史
```bash
# 查看提交日志
git log
git log --oneline        # 简洁格式
git log --graph          # 图形化分支
git log --stat           # 显示文件统计

# 查看某次提交的改动
git show <commit-hash>
```

### 分支管理
```bash
# 查看分支
git branch
git branch -a            # 包括远程分支

# 创建分支
git branch <branch-name>

# 切换分支
git checkout <branch-name>
git checkout -b <branch-name>  # 创建并切换

# 合并分支
git checkout main
git merge <branch-name>

# 删除分支
git branch -d <branch-name>   # 删除已合并的分支
git branch -D <branch-name>   # 强制删除
```

## 远程操作

```bash
# 查看远程仓库
git remote -v

# 添加远程仓库
git remote add origin <url>

# 拉取最新代码
git pull origin main

# 推送代码
git push origin main

# 推送新分支
git push -u origin <branch-name>

# 拉取远程新分支
git fetch
git checkout -b <branch-name> origin/<branch-name>
```

## 撤销操作

```bash
# 撤销工作区改动
git checkout -- <file>

# 撤销暂存区改动
git reset HEAD <file>

# 回退到某个版本（保留改动）
git reset <commit-hash>

# 回退到某个版本（丢弃改动）
git reset --hard <commit-hash>

# 恢复已删除的文件
git checkout <commit-hash> -- <file>
```

## 解决冲突

```bash
# 查看冲突文件
git status

# 手动编辑冲突文件后
git add <file>
git commit
```

## .gitignore 常用规则

```gitignore
# 忽略目录
node_modules/
__pycache__/
.env
.vscode/

# 忽略文件类型
*.log
*.pyc
*.egg-info/
.DS_Store

# 保留特定文件
!README.md
```

## 项目常用命令

```bash
# 查看当前分支和状态
git branch && echo "---" && git status

# 查看最近提交
git log --oneline -5

# 更新本地代码
git fetch origin
git pull origin main
```
