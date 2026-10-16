<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import CompassioLogo from '@/components/CompassioLogo.vue'

const router = useRouter()
const auth = useAuthStore()

// 已登录用户：直接按角色分流（保持与旧 HomeRedirect 一致的行为）
if (auth.isLoggedIn) {
  if (auth.isAdmin) router.replace('/admin/notifications')
  else if (auth.isTeacher) router.replace('/teacher')
  else if (auth.isStudent) router.replace('/student')
  else router.replace('/login')
}

function goLogin() {
  router.push('/login')
}

interface Advantage {
  icon: string
  title: string
  desc: string
}

const advantages: Advantage[] = [
  {
    icon: 'MagicStick',
    title: '大模型驱动',
    desc: '依据作答实时调整出题节奏，检查点动态重排；生成非诊断、正向框架的发展性反馈。'
  },
  {
    icon: 'Lock',
    title: '计分绝不外包',
    desc: '计分是纯确定性引擎，严格按量表定义执行；大模型只负责措辞，不参与判分。'
  },
  {
    icon: 'Bell',
    title: '危机预警',
    desc: '命中极端风险题（如 MHT 85/97）第一时间通知校级管理员，站内 + 顶部横幅。'
  },
  {
    icon: 'View',
    title: '隐私优先',
    desc: '学生数据按班级最小化可见；教师数据仅本人可见；全程保留审计日志。'
  },
  {
    icon: 'Money',
    title: '成本可控',
    desc: '融合策略：一份 100 题 MHT 约 5–8 次大模型调用，而非 84 次；可一键关闭。'
  },
  {
    icon: 'Box',
    title: '一键部署',
    desc: 'docker compose 四条命令起；亦可接入 K8s + GitOps（ArgoCD）滚动发布。'
  }
]

const scales = [
  {
    name: 'MHT 心理健康诊断测验',
    audience: '小学四年级至高中',
    structure: '100 题 · 8 个内容量表 + 效度量表（测谎 10 题，≥7 作废）',
    scoring: '是=1 否=0；总分 ≤55 正常 / 56–64 欠佳 / ≥65 重点；单维度 ≤3 / 4–7 / ≥8 分级'
  },
  {
    name: 'MSSMHS 中学生心理健康量表',
    audience: '初中 / 高中',
    structure: '60 题 × 10 维度',
    scoring: '1–5 分；因子分 ≥2 提示问题，≥3 中度及以上'
  },
  {
    name: '教师心理健康评价量表（参考版）',
    audience: '教师',
    structure: '60 题 × 4 维度（自我 / 社会 / 工作 / 生活）',
    scoring: '分数越高，心理健康资源越充分'
  }
]

const roles = [
  { icon: 'Setting', name: '校级管理员', desc: '导入师生名单 → 自动建号；查看完成率 / 维度均值、导出结果、接收危机预警。' },
  { icon: 'Reading', name: '班主任（教师）', desc: '本班学生答完即自动可见，可查看 / 打印 / 导出本班结果。' },
  { icon: 'User', name: '学生', desc: '登录后选择合适的量表作答，全程单题呈现、断点续答，完成后查看本人报告。' },
  { icon: 'UserFilled', name: '教师本人', desc: '填写教师量表，结果仅本人可见，任何管理员不可见。' }
]
</script>

<template>
  <div class="landing">
    <!-- Hero -->
    <section class="hero">
      <div class="hero-inner">
        <div class="hero-badge">Heart Education Compass for Schools</div>
        <div class="hero-logo"><CompassioLogo :size="72" /></div>
        <h1 class="hero-title">Compassio · 心育罗盘</h1>
        <p class="hero-slogan">提前指引，向阳成长。<span class="en">Guide early. Grow strong.</span></p>
        <p class="hero-quote">我们不贴标签、不制造焦虑。每一次测评，都只是一次温柔地看见自己。</p>
        <div class="hero-actions">
          <el-button type="primary" size="large" round @click="goLogin">
            <el-icon><Compass /></el-icon> 进入系统
          </el-button>
          <a class="ghost" href="#features">了解它能做什么</a>
        </div>
        <div class="hero-stats">
          <div class="stat"><strong>3</strong><span>套测评量表</span></div>
          <div class="stat"><strong>10</strong><span>个心理维度</span></div>
          <div class="stat"><strong>5–8</strong><span>次/份 LLM 调用</span></div>
          <div class="stat"><strong>100%</strong><span>纯确定性计分</span></div>
        </div>
      </div>
    </section>

    <!-- 系统简介 -->
    <section class="section about">
      <h2 class="section-title">系统简介</h2>
      <p class="about-text">
        Compassio 是一个由大模型驱动的<strong>校级心理健康测评系统</strong>：既是指引方向的
        <strong>罗盘</strong>，也是带着关怀去守护成长的陪伴。它为学校提供从
        <strong>导入名单 → 自动建号 → 在线作答 → 发展性反馈 → 班级报告 → 危机预警</strong>
        的一体化闭环，让心理健康工作更早看见、更快响应。
      </p>
      <div class="about-cards">
        <div class="about-card">
          <el-icon class="about-ic"><Compass /></el-icon>
          <h3>指引方向</h3>
          <p>以发展性视角呈现结果，帮助学校与家庭更早地看见需要支持的孩子。</p>
        </div>
        <div class="about-card">
          <el-icon class="about-ic"><Aim /></el-icon>
          <h3>精准筛选</h3>
          <p>三套权威量表 + 纯确定性计分，分级清晰、口径统一、可追溯。</p>
        </div>
        <div class="about-card">
          <el-icon class="about-ic"><Sunny /></el-icon>
          <h3>向阳成长</h3>
          <p>非诊断、正向框架的语言，配合可执行建议与求助渠道，温柔而专业。</p>
        </div>
      </div>
    </section>

    <!-- 核心优势 -->
    <section id="features" class="section features">
      <h2 class="section-title">核心优势</h2>
      <div class="grid">
        <div v-for="a in advantages" :key="a.title" class="feature-card">
          <div class="feature-ic"><component :is="a.icon" /></div>
          <h3>{{ a.title }}</h3>
          <p>{{ a.desc }}</p>
        </div>
      </div>
    </section>

    <!-- 三套量表 -->
    <section class="section scales">
      <h2 class="section-title">三套测评量表</h2>
      <div class="scale-cards">
        <div v-for="(s, i) in scales" :key="s.name" class="scale-card">
          <div class="scale-index">{{ i + 1 }}</div>
          <h3>{{ s.name }}</h3>
          <p class="scale-meta"><span>对象</span>{{ s.audience }}</p>
          <p class="scale-meta"><span>结构</span>{{ s.structure }}</p>
          <p class="scale-meta"><span>计分</span>{{ s.scoring }}</p>
        </div>
      </div>
    </section>

    <!-- 谁在使用 -->
    <section class="section roles">
      <h2 class="section-title">谁能用上它</h2>
      <div class="role-grid">
        <div v-for="r in roles" :key="r.name" class="role-card">
          <el-icon class="role-ic"><component :is="r.icon" /></el-icon>
          <div>
            <h3>{{ r.name }}</h3>
            <p>{{ r.desc }}</p>
          </div>
        </div>
      </div>
    </section>

    <!-- CTA -->
    <section class="cta">
      <h2>让每一次测评，都成为一次温柔的看见</h2>
      <p>发展性筛查参考，不构成医学诊断。</p>
      <el-button type="primary" size="large" round @click="goLogin">
        <el-icon><Compass /></el-icon> 登录 / 开始使用
      </el-button>
    </section>

    <footer class="landing-footer">
      <p>Compassio © 2026 提前指引，向阳成长。</p>
      <p class="muted">Heart Education Compass for Schools</p>
    </footer>
  </div>
</template>

<style scoped>
.landing {
  max-width: 1120px;
  margin: 0 auto;
  padding: 0 4px 40px;
}

/* Hero */
.hero {
  position: relative;
  margin: 8px 0 40px;
  border-radius: 24px;
  overflow: hidden;
  background: radial-gradient(1200px 400px at 50% -10%, #dbeafe 0%, #eff6ff 45%, #ffffff 100%);
  border: 1px solid #e0e7ff;
}
.hero-inner {
  padding: 56px 32px 40px;
  text-align: center;
}
.hero-badge {
  display: inline-block;
  font-size: 12px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #2563eb;
  background: #e0edff;
  padding: 6px 14px;
  border-radius: 999px;
  margin-bottom: 20px;
}
.hero-logo {
  display: flex;
  justify-content: center;
  animation: floaty 4s ease-in-out infinite;
}
.hero-title {
  margin: 14px 0 6px;
  font-size: 40px;
  letter-spacing: 0.02em;
  color: #0f172a;
}
.hero-slogan {
  font-size: 18px;
  color: #1d4ed8;
  margin: 0 0 10px;
  font-weight: 600;
}
.hero-slogan .en {
  font-weight: 400;
  color: #64748b;
  font-size: 14px;
  margin-left: 8px;
}
.hero-quote {
  max-width: 640px;
  margin: 0 auto 26px;
  color: #475569;
  line-height: 1.7;
}
.hero-actions {
  display: flex;
  gap: 14px;
  justify-content: center;
  align-items: center;
  flex-wrap: wrap;
}
.hero-actions .ghost {
  color: #2563eb;
  font-size: 14px;
  text-decoration: none;
  border-bottom: 1px dashed #93c5fd;
  padding-bottom: 2px;
}
.hero-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  max-width: 720px;
  margin: 36px auto 0;
}
.stat {
  background: #ffffffcc;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 14px 8px;
}
.stat strong {
  display: block;
  font-size: 24px;
  color: #1d4ed8;
}
.stat span {
  font-size: 12px;
  color: #64748b;
}
@keyframes floaty {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}

/* Sections */
.section {
  margin: 48px 0;
}
.section-title {
  font-size: 26px;
  text-align: center;
  color: #0f172a;
  margin: 0 0 28px;
  position: relative;
}
.section-title::after {
  content: '';
  display: block;
  width: 48px;
  height: 4px;
  border-radius: 4px;
  background: linear-gradient(90deg, #3b82f6, #22d3ee);
  margin: 12px auto 0;
}

/* About */
.about-text {
  max-width: 860px;
  margin: 0 auto 28px;
  text-align: center;
  color: #475569;
  line-height: 1.9;
  font-size: 15px;
}
.about-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
}
.about-card {
  background: #fff;
  border: 1px solid #eef2f7;
  border-radius: 16px;
  padding: 24px;
  text-align: center;
  box-shadow: 0 6px 20px rgba(15, 23, 42, 0.04);
}
.about-ic {
  font-size: 30px;
  color: #3b82f6;
}
.about-card h3 {
  margin: 12px 0 8px;
  color: #0f172a;
}
.about-card p {
  margin: 0;
  color: #64748b;
  font-size: 14px;
  line-height: 1.7;
}

/* Features */
.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
}
.feature-card {
  background: #fff;
  border: 1px solid #eef2f7;
  border-radius: 16px;
  padding: 24px;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.feature-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 14px 30px rgba(37, 99, 235, 0.1);
}
.feature-ic {
  width: 46px;
  height: 46px;
  border-radius: 12px;
  background: linear-gradient(135deg, #dbeafe, #e0f2fe);
  color: #2563eb;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  margin-bottom: 14px;
}
.feature-card h3 {
  margin: 0 0 8px;
  color: #0f172a;
  font-size: 17px;
}
.feature-card p {
  margin: 0;
  color: #64748b;
  font-size: 14px;
  line-height: 1.7;
}

/* Scales */
.scale-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
}
.scale-card {
  position: relative;
  background: linear-gradient(180deg, #ffffff, #f8fbff);
  border: 1px solid #e6eefb;
  border-radius: 16px;
  padding: 26px 22px 22px;
}
.scale-index {
  position: absolute;
  top: -14px;
  left: 22px;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #2563eb;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}
.scale-card h3 {
  margin: 8px 0 14px;
  font-size: 16px;
  color: #0f172a;
}
.scale-meta {
  margin: 6px 0;
  font-size: 13px;
  color: #475569;
  line-height: 1.6;
}
.scale-meta span {
  display: inline-block;
  min-width: 40px;
  color: #94a3b8;
  margin-right: 8px;
}

/* Roles */
.role-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}
.role-card {
  display: flex;
  gap: 16px;
  background: #fff;
  border: 1px solid #eef2f7;
  border-radius: 14px;
  padding: 20px;
}
.role-ic {
  font-size: 24px;
  color: #3b82f6;
  margin-top: 2px;
}
.role-card h3 {
  margin: 0 0 6px;
  font-size: 16px;
  color: #0f172a;
}
.role-card p {
  margin: 0;
  color: #64748b;
  font-size: 14px;
  line-height: 1.7;
}

/* CTA */
.cta {
  text-align: center;
  margin: 56px 0 24px;
  padding: 44px 24px;
  border-radius: 24px;
  background: linear-gradient(135deg, #1d4ed8, #0ea5e9);
  color: #fff;
}
.cta h2 {
  margin: 0 0 10px;
  font-size: 26px;
}
.cta p {
  margin: 0 0 22px;
  opacity: 0.9;
  font-size: 14px;
}
.cta .el-button {
  color: #1d4ed8;
  background: #fff;
  border: none;
  font-weight: 600;
}

.landing-footer {
  text-align: center;
  color: #94a3b8;
  font-size: 13px;
  margin-top: 28px;
}
.landing-footer .muted {
  font-size: 12px;
  letter-spacing: 0.08em;
}

@media (max-width: 900px) {
  .hero-title { font-size: 30px; }
  .hero-stats { grid-template-columns: repeat(2, 1fr); }
  .about-cards,
  .grid,
  .scale-cards { grid-template-columns: 1fr; }
  .role-grid { grid-template-columns: 1fr; }
}
</style>
