let currentScheduleList = [];
let currentViewingScheduleId = null;
let currentView = 'calendar';

function switchView(viewType){
    currentView = viewType;
    document.querySelectorAll('.view-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById(viewType + 'ViewBtn').classList.add('active');
    document.querySelectorAll('.view-container').forEach(container => {
        container.style.display = 'none';
    });
    const viewContainer = document.getElementById(viewType + 'View');
    if(viewContainer){
        viewContainer.style.display = 'block';
    }
    refreshSchedule();
}

function createParticles(){
    const container = document.getElementById('particles');
    if(!container) return;
    const count = 15;
    for(let i=0; i<count; i++){
        const particle = document.createElement('div');
        particle.className = 'particle';
        const size = Math.random() * 40 + 20;
        particle.style.width = size + 'px';
        particle.style.height = size + 'px';
        particle.style.left = Math.random() * 100 + '%';
        particle.style.animationDelay = Math.random() * 8 + 's';
        particle.style.animationDuration = (Math.random() * 4 + 6) + 's';
        container.appendChild(particle);
    }
}

window.onload = async function(){
    initTheme();
    createParticles();
    document.getElementById("yearSel").value = nowYear;
    document.getElementById("monthSel").value = nowMonth;
    await loadSiteConfig();
    loadStats();
    loadRanking();
    loadFriendLinks();
    renderNav();
    fetchUserNickname();
    await checkApplyStatus();
    refreshSchedule();
    refreshRoleBtn();
    loadMyReservations();
    loadMainForumComments();
    checkInboxUnread();
    // 每30秒刷新一次未读邮件数量
    setInterval(checkInboxUnread, 30000);
}

async function loadSiteConfig() {
    try {
        const resp = await fetch("/get_site_config", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({})});
        const data = await resp.json();
        if (data.ok) {
            if (data.configs.site_title) document.getElementById("siteTitle").textContent = data.configs.site_title;
            if (data.configs.site_announcement) document.getElementById("siteAnnouncement").textContent = "公告：" + data.configs.site_announcement;
            if (data.configs.footer_text) document.querySelector(".footer-text").textContent = data.configs.footer_text;
            const localBgImage = localStorage.getItem('localBackgroundImage');
            if (localBgImage) {
                const bgLayer = document.getElementById('bg-image-layer');
                if (bgLayer) {
                    bgLayer.style.backgroundImage = 'url(' + localBgImage + ')';
                    bgLayer.classList.add('active');
                }
            } else if (data.configs.background_image) {
                const bgLayer = document.getElementById('bg-image-layer');
                if (bgLayer) {
                    bgLayer.style.backgroundImage = 'url(' + data.configs.background_image + ')';
                    bgLayer.classList.add('active');
                }
            }
            if (data.configs.maintenance_mode === "1" && currentRole < ROLE_ADMIN) {
                showMaintenanceModal(data.configs.maintenance_message || "网站正在维护中，请稍后再试...");
            }
        }
    } catch (e) { console.error("加载网站配置失败:", e); }
}

function showMaintenanceModal(message) {
    document.getElementById("maintenanceMessage").textContent = message;
    openModal("maintenanceModal");
}

async function loadStats() {
    try {
        const resp = await fetch("/get_stats", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({})});
        const data = await resp.json();
        if (data.ok && data.show) {
            document.getElementById("totalUser").textContent = data.total_user;
            document.getElementById("normalUser").textContent = data.normal_user;
            document.getElementById("opUser").textContent = data.op_user;
            document.getElementById("adminUser").textContent = data.admin_user;
            document.getElementById("statsCard").style.display = "block";
        } else {
            document.getElementById("statsCard").style.display = "none";
        }
    } catch (e) { console.error("加载统计数据失败:", e); }
}

async function loadRanking() {
    try {
        const resp = await fetch("/get_reservation_ranking", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({})});
        const data = await resp.json();
        if (!data.ok || !data.show) {
            document.getElementById("rankingCard").style.display = "none";
            return;
        }
        document.getElementById("rankingCard").style.display = "block";
        if (data.year_ranking && data.year_ranking.length > 0) {
            let yearHtml = '';
            data.year_ranking.slice(0, 5).forEach((item, index) => {
                const medals = ['🥇', '🥈', '🥉'];
                const rankSymbol = index < 3 ? medals[index] : (index + 1);
                yearHtml += `<div class="ranking-item" onclick="jumpToSchedule(${item.schedule_id})"><span class="rank">${rankSymbol}</span>${item.server_id.substring(0, 8)}<span class="count">${item.count}人</span></div>`;
            });
            document.getElementById("yearRanking").innerHTML = yearHtml || '<div class="empty-tip">暂无数据</div>';
        } else {
            document.getElementById("yearRanking").innerHTML = '<div class="empty-tip">暂无数据</div>';
        }
        if (data.month_ranking && data.month_ranking.length > 0) {
            let monthHtml = '';
            data.month_ranking.slice(0, 5).forEach((item, index) => {
                const medals = ['🥇', '🥈', '🥉'];
                const rankSymbol = index < 3 ? medals[index] : (index + 1);
                monthHtml += `<div class="ranking-item" onclick="jumpToSchedule(${item.schedule_id})"><span class="rank">${rankSymbol}</span>${item.server_id.substring(0, 8)}<span class="count">${item.count}人</span></div>`;
            });
            document.getElementById("monthRanking").innerHTML = monthHtml || '<div class="empty-tip">暂无数据</div>';
        } else {
            document.getElementById("monthRanking").innerHTML = '<div class="empty-tip">暂无数据</div>';
        }
    } catch (e) { console.error("加载排行榜失败:", e); }
}

async function loadFriendLinks() {
    try {
        const resp = await fetch("/get_friend_links");
        const data = await resp.json();
        if (data.show === false) {
            const card = document.getElementById("friendLinksCard");
            if (card) card.style.display = "none";
            return;
        }
        if (data.ok === 1 && data.links && data.links.length > 0) {
            let html = '';
            data.links.forEach(link => {
                const iconHtml = link.icon 
                    ? `<img src="${link.icon}" alt="${link.name}" onerror="this.outerHTML='<span class=\\'link-icon\\'>🔗</span>'">` 
                    : `<span class="link-icon">🔗</span>`;
                const title = link.description ? link.description : link.name;
                html += `<a href="${link.url}" class="friend-link-item" target="_blank" title="${title}">${iconHtml}<span>${link.name}</span></a>`;
            });
            document.getElementById("friendLinksList").innerHTML = html;
        } else {
            document.getElementById("friendLinksList").innerHTML = '<div class="empty-tip">暂无友链</div>';
        }
    } catch (e) { 
        console.error("加载友链失败:", e);
        document.getElementById("friendLinksList").innerHTML = '<div class="empty-tip">加载失败</div>';
    }
}

let currentRankingView = 'year';

function switchRanking(view) {
    currentRankingView = view;
    document.getElementById("yearRankBtn").classList.toggle("active", view === "year");
    document.getElementById("monthRankBtn").classList.toggle("active", view === "month");
    document.getElementById("yearRanking").style.display = view === "year" ? "block" : "none";
    document.getElementById("monthRanking").style.display = view === "month" ? "block" : "none";
}

function jumpToSchedule(scheduleId) {
    showScheduleDetail(scheduleId);
}

document.querySelectorAll('.modal').forEach(modal => {
    modal.addEventListener('click', function(e) {
        if (e.target === this) {
            closeModal(this.id);
        }
    });
});

function getDisplayName(){
    const savedNickname = localStorage.getItem('user_nickname');
    if(savedNickname && savedNickname !== "null" && savedNickname !== "undefined"){
        return savedNickname;
    }
    return currentUser;
}

async function fetchUserNickname(){
    if(!currentUser || currentUser === "" || currentUser === "None") return;
    try{
        const res = await fetch("/user/info", {method: "POST"});
        const data = await res.json();
        if(data.ok === 1 && data.nickname){
            localStorage.setItem('user_nickname', data.nickname);
            renderNav();
        }
    }catch(e){
        console.error("获取用户信息失败:", e);
    }
}

function renderNav(){
    const navBox = document.getElementById("navBox");
    const isLoggedIn = currentUser && currentUser !== "" && currentUser !== "None";
    if(isLoggedIn){
        const displayName = getDisplayName();
        const firstChar = displayName.charAt(0).toUpperCase();
        navBox.innerHTML = `
            <div class="user-dropdown-container">
                <div class="user-dropdown-trigger" onclick="toggleUserDropdown()">
                    <div class="user-avatar">${firstChar}</div>
                    <span>${displayName}</span>
                    <span style="font-size:12px;opacity:0.6;">▼</span>
                </div>
                <div class="user-dropdown-menu" id="userDropdownMenu">
                    <div class="user-dropdown-item" onclick="openProfile();closeUserDropdown()">
                        👤 个人中心
                    </div>
                    <div class="user-dropdown-item" onclick="openBgSettings();closeUserDropdown()">
                        🎨 背景设置
                    </div>
                    <div class="user-dropdown-item" onclick="openInbox();closeUserDropdown()">
                        📧 站内邮件 <span id="inboxUnreadCount" style="background:#E74C3C;border-radius:10px;padding:0 5px;font-size:10px;display:none;">0</span>
                    </div>
                    <div class="user-dropdown-divider"></div>
                    <div class="user-dropdown-item" onclick="logout()">
                        🚪 退出登录
                    </div>
                </div>
            </div>
        `;
    }else{
        navBox.innerHTML = `
            <button onclick="openLogin()">登录</button>
            <button onclick="openRegister()">注册</button>
        `;
    }
}

function toggleUserDropdown(){
    const menu = document.getElementById("userDropdownMenu");
    const trigger = document.querySelector(".user-dropdown-trigger");
    if(menu && trigger){
        menu.classList.toggle("show");
        trigger.classList.toggle("active");
    }
}

function closeUserDropdown(){
    const menu = document.getElementById("userDropdownMenu");
    const trigger = document.querySelector(".user-dropdown-trigger");
    if(menu && trigger){
        menu.classList.remove("show");
        trigger.classList.remove("active");
    }
}

document.addEventListener("click", function(e){
    const container = document.querySelector(".user-dropdown-container");
    if(container && !container.contains(e.target)){
        closeUserDropdown();
    }
});

function refreshRoleBtn(){
    const addBtn = document.getElementById("addBtn");
    const applyOpBtn = document.getElementById("applyOpBtn");
    const adminBtn = document.getElementById("adminBtn");
    const isLoggedIn = currentUser && currentUser !== "" && currentUser !== "None";
    if(!isLoggedIn){
        addBtn.style.display = "none";
        applyOpBtn.style.display = "none";
        adminBtn.style.display = "none";
        return;
    }
    if(currentRole === ROLE_OP || currentRole === ROLE_TRUSTED_OP || currentRole === ROLE_ADMIN || currentRole === ROLE_SUPER_ADMIN){
        addBtn.style.display = "inline-block";
        applyOpBtn.style.display = "none";
    }else{
        addBtn.style.display = "none";
        if(currentApplyStatus === 0){
            applyOpBtn.style.display = "inline-block";
            applyOpBtn.innerText = "审核中...";
            applyOpBtn.disabled = true;
            applyOpBtn.style.background = "#666";
            applyOpBtn.style.cursor = "not-allowed";
        }else if(currentApplyStatus === 3){
            applyOpBtn.style.display = "inline-block";
            applyOpBtn.innerText = "成为档主";
            applyOpBtn.disabled = false;
            applyOpBtn.style.background = "#9B59B6";
            applyOpBtn.style.cursor = "pointer";
        }else{
            applyOpBtn.style.display = "none";
        }
    }
    if(currentRole === ROLE_ADMIN || currentRole === ROLE_SUPER_ADMIN){
        adminBtn.style.display = "inline-block";
    }else{
        adminBtn.style.display = "none";
    }
}

function openLogin(){
    openModal("loginModal");
    document.getElementById("regModal").style.display = "none";
    document.getElementById("forgotModal").style.display = "none";
    document.getElementById("registerNoticeModal").style.display = "none";
    document.getElementById("loginMsg").innerText = "";
}
function openRegister(){
    document.getElementById("loginModal").style.display = "none";
    document.getElementById("regModal").style.display = "none";
    document.getElementById("forgotModal").style.display = "none";
    openModal("registerNoticeModal");
    document.getElementById("agreeRegisterNotice").checked = false;
    document.getElementById("registerAgreeBtn").disabled = true;
    document.getElementById("regMsg").innerText = "";
}
function openForgot(){
    openModal("forgotModal");
    document.getElementById("loginModal").style.display = "none";
    document.getElementById("regModal").style.display = "none";
    document.getElementById("forgotMsg").innerText = "";
}
function switchModal(type){
    if(type === "login") openLogin();
    else if(type === "reg") openRegister();
    else if(type === "forgot") openForgot();
}
function openAddModal(){
    openModal("addScheduleModal");
    loadScheduleTags();
    document.getElementById("endDateContainer").style.display = "none";
    document.getElementById("scheduleTime").onchange = function(){
        const customInput = document.getElementById("scheduleTimeCustom");
        if(this.value === "其他"){
            customInput.style.display = "block";
            customInput.focus();
        } else {
            customInput.style.display = "none";
            customInput.value = "";
        }
    };
}

function toggleEndDate() {
    const type = document.getElementById("scheduleType").value;
    const endDateContainer = document.getElementById("endDateContainer");
    if (type === "long") {
        endDateContainer.style.display = "block";
    } else {
        endDateContainer.style.display = "none";
        document.getElementById("scheduleEndDate").value = "";
    }
}

async function loadScheduleTags(){
    try {
        const res = await fetch("/get_tags", {
            method: "POST",
            headers: {"Content-Type": "application/json"}
        });
        const data = await res.json();
        const select = document.getElementById("scheduleTagSelect");
        if(data.ok === 1 && data.data && data.data.length > 0) {
            let html = '<option value="">请选择标签</option>';
            data.data.forEach(tag => {
                html += `<option value="${tag.id}" style="color:${tag.color}">${tag.name}</option>`;
            });
            select.innerHTML = html;
        } else {
            select.innerHTML = '<option value="">暂无标签</option>';
        }
    } catch(e) {
        console.error("加载标签失败:", e);
        document.getElementById("scheduleTagSelect").innerHTML = '<option value="">加载失败</option>';
    }
}
function openModal(id){
    const modal = document.getElementById(id);
    if(modal){
        modal.style.display = "flex";
        setTimeout(() => modal.classList.add('show'), 10);
    }
}
function closeModal(id){
    if(id === 'serverStatusModal') {
        closeServerStatusModal();
    } else {
        const modal = document.getElementById(id);
        if(modal){
            modal.classList.remove('show');
            setTimeout(() => modal.style.display = "none", 300);
        }
    }
}

async function getCode(){
    const email = document.getElementById("regEmail").value.trim();
    if(!email){
        document.getElementById("regMsg").innerText = "请填写邮箱";
        return;
    }
    const res = await fetch("/send_code",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({email:email})
    });
    const data = await res.json();
    if(data.ok === 1){
        document.getElementById("regMsg").innerText = "验证码已发送，请查收邮箱（15分钟内有效）";
        document.getElementById("regMsg").style.color = "#2ECC71";
    }else{
        document.getElementById("regMsg").innerText = data.msg;
    }
}

let resetCodeCooldown = 0;
async function sendResetCode(){
    if(resetCodeCooldown > 0){
        document.getElementById("forgotMsg").innerText = `请 ${resetCodeCooldown} 秒后再试`;
        return;
    }
    const email = document.getElementById("forgotEmail").value.trim();
    if(!email){
        document.getElementById("forgotMsg").innerText = "请输入邮箱地址";
        return;
    }
    const btn = document.getElementById("sendResetCodeBtn");
    btn.disabled = true;
    btn.innerText = "发送中...";
    try{
        const res = await fetch("/send_reset_code",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({email})
        });
        const data = await res.json();
        if(data.ok === 1){
            document.getElementById("forgotMsg").innerText = "验证码已发送到邮箱";
            resetCodeCooldown = 60;
            const timer = setInterval(() => {
                resetCodeCooldown--;
                if(resetCodeCooldown <= 0){
                    clearInterval(timer);
                    btn.disabled = false;
                    btn.innerText = "获取验证码";
                }else{
                    btn.innerText = `${resetCodeCooldown}秒后重试`;
                }
            }, 1000);
        }else{
            document.getElementById("forgotMsg").innerText = data.msg;
            btn.disabled = false;
            btn.innerText = "获取验证码";
        }
    }catch(e){
        document.getElementById("forgotMsg").innerText = "发送失败，请稍后重试";
        btn.disabled = false;
        btn.innerText = "获取验证码";
    }
}

async function doResetPassword(){
    const email = document.getElementById("forgotEmail").value.trim();
    const code = document.getElementById("forgotCode").value.trim();
    const newPassword = document.getElementById("forgotNewPwd").value.trim();
    const confirmPwd = document.getElementById("forgotConfirmPwd").value.trim();
    if(!email || !code || !newPassword || !confirmPwd){
        document.getElementById("forgotMsg").innerText = "请填写完整所有信息";
        return;
    }
    if(newPassword !== confirmPwd){
        document.getElementById("forgotMsg").innerText = "两次密码输入不一致";
        return;
    }
    if(newPassword.length < 6){
        document.getElementById("forgotMsg").innerText = "密码长度至少需要6位";
        return;
    }
    const res = await fetch("/reset_password",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({email, code, new_password: newPassword})
    });
    const data = await res.json();
    if(data.ok === 1){
        alert("密码重置成功，请登录");
        openLogin();
    }else{
        document.getElementById("forgotMsg").innerText = data.msg;
    }
}

async function openProfile(){
    try{
        const res = await fetch("/user/info", {method: "POST"});
        const data = await res.json();
        if(data.ok === 1){
            document.getElementById("profileNickname").innerText = data.nickname;
            document.getElementById("profileEmail").innerText = data.email;
            openModal("profileModal");
            document.getElementById("profileMsg").innerText = "";
            hideEditNickname();
            document.getElementById("profileOldPwd").value = "";
            document.getElementById("profileNewPwd").value = "";
        }else{
            alert("获取用户信息失败：" + data.msg);
        }
    }catch(e){
        console.error("获取用户信息失败:", e);
        alert("获取用户信息失败");
    }
}

function openBgSettings() {
    const currentBg = localStorage.getItem('localBackgroundImage') || '';
    document.getElementById('bgUrlInput').value = currentBg;
    if (currentBg) {
        const previewImg = document.getElementById('bgPreviewImg');
        previewImg.src = currentBg;
        document.getElementById('bgPreview').style.display = 'block';
    } else {
        document.getElementById('bgPreview').style.display = 'none';
    }
    openModal('bgSettingsModal');
    document.getElementById('bgSettingsMsg').textContent = '';
}

function previewLocalBg() {
    const url = document.getElementById('bgUrlInput').value.trim();
    if (!url) {
        document.getElementById('bgSettingsMsg').textContent = '请输入图片URL';
        document.getElementById('bgSettingsMsg').style.color = '#ff6b6b';
        return;
    }
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
        document.getElementById('bgSettingsMsg').textContent = '请输入有效的URL（以http://或https://开头）';
        document.getElementById('bgSettingsMsg').style.color = '#ff6b6b';
        return;
    }
    const previewImg = document.getElementById('bgPreviewImg');
    previewImg.onload = function() {
        document.getElementById('bgPreview').style.display = 'block';
        document.getElementById('bgSettingsMsg').textContent = '✅ 预览成功';
        document.getElementById('bgSettingsMsg').style.color = '#2ECC71';
    };
    previewImg.onerror = function() {
        document.getElementById('bgSettingsMsg').textContent = '❌ 图片加载失败';
        document.getElementById('bgSettingsMsg').style.color = '#ff6b6b';
    };
    previewImg.src = url;
}

function saveLocalBg() {
    const url = document.getElementById('bgUrlInput').value.trim();
    if (!url) {
        document.getElementById('bgSettingsMsg').textContent = '请输入图片URL';
        document.getElementById('bgSettingsMsg').style.color = '#ff6b6b';
        return;
    }
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
        document.getElementById('bgSettingsMsg').textContent = '请输入有效的URL（以http://或https://开头）';
        document.getElementById('bgSettingsMsg').style.color = '#ff6b6b';
        return;
    }
    localStorage.setItem('localBackgroundImage', url);
    const bgLayer = document.getElementById('bg-image-layer');
    if (bgLayer) {
        bgLayer.style.backgroundImage = 'url(' + url + ')';
        bgLayer.classList.add('active');
    }
    document.getElementById('bgSettingsMsg').textContent = '✅ 背景已保存！仅对您自己可见';
    document.getElementById('bgSettingsMsg').style.color = '#2ECC71';
}

function clearLocalBg() {
    localStorage.removeItem('localBackgroundImage');
    document.getElementById('bgUrlInput').value = '';
    document.getElementById('bgPreview').style.display = 'none';
    loadSiteConfig();
    document.getElementById('bgSettingsMsg').textContent = '✅ 已清除本地背景，恢复默认';
    document.getElementById('bgSettingsMsg').style.color = '#2ECC71';
}

function setTheme(mode) {
    localStorage.setItem('theme', mode);
    applyTheme(mode);
    updateThemeButtons(mode);
    document.getElementById('bgSettingsMsg').textContent = '✅ 主题已切换';
    document.getElementById('bgSettingsMsg').style.color = '#2ECC71';
}

function applyTheme(mode) {
    const isDark = (mode === 'dark') || (mode === 'auto' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    if (isDark) {
        document.body.classList.remove('light-mode');
    } else {
        document.body.classList.add('light-mode');
    }
}

function updateThemeButtons(mode) {
    const darkBtn = document.getElementById('themeDarkBtn');
    const lightBtn = document.getElementById('themeLightBtn');
    const autoBtn = document.getElementById('themeAutoBtn');
    const activeStyle = 'flex:1;padding:6px;font-size:12px;border-radius:6px;border:none;background:#3498db;color:#fff;cursor:pointer;';
    const inactiveStyle = 'flex:1;padding:6px;font-size:12px;border-radius:6px;border:none;background:#555;color:#fff;cursor:pointer;';
    darkBtn.style = mode === 'dark' ? activeStyle : inactiveStyle;
    lightBtn.style = mode === 'light' ? activeStyle : inactiveStyle;
    autoBtn.style = mode === 'auto' ? activeStyle : inactiveStyle;
}

function initTheme() {
    const savedMode = localStorage.getItem('theme') || 'auto';
    applyTheme(savedMode);
    updateThemeButtons(savedMode);
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        if (localStorage.getItem('theme') === 'auto') {
            applyTheme('auto');
        }
    });
}

function resetAllSettings() {
    if (confirm('确定要重置所有本地设置吗？这将清除背景图片和主题设置。')) {
        localStorage.removeItem('localBackgroundImage');
        localStorage.removeItem('theme');
        applyTheme('auto');
        updateThemeButtons('auto');
        loadSiteConfig();
        document.getElementById('bgUrlInput').value = '';
        document.getElementById('bgPreview').style.display = 'none';
        document.getElementById('bgSettingsMsg').textContent = '✅ 所有设置已重置';
        document.getElementById('bgSettingsMsg').style.color = '#2ECC71';
    }
}

function showEditNickname(){
    const currentNickname = document.getElementById("profileNickname").innerText;
    document.getElementById("newNickname").value = currentNickname;
    document.getElementById("editNicknameArea").style.display = "block";
}

function hideEditNickname(){
    document.getElementById("editNicknameArea").style.display = "none";
    document.getElementById("newNickname").value = "";
}

async function saveNickname(){
    const newNickname = document.getElementById("newNickname").value.trim();
    if(!newNickname){
        document.getElementById("profileMsg").innerText = "请输入新昵称";
        document.getElementById("profileMsg").style.color = "#E74C3C";
        return;
    }
    if(newNickname.length < 2 || newNickname.length > 20){
        document.getElementById("profileMsg").innerText = "昵称需在2-20个字符之间";
        document.getElementById("profileMsg").style.color = "#E74C3C";
        return;
    }
    try{
        const res = await fetch("/user/update_nickname", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({nickname: newNickname})
        });
        const data = await res.json();
        if(data.ok === 1){
            document.getElementById("profileNickname").innerText = newNickname;
            localStorage.setItem('user_nickname', newNickname);
            renderNav();
            hideEditNickname();
            document.getElementById("profileMsg").innerText = "昵称修改成功！";
            document.getElementById("profileMsg").style.color = "#2ECC71";
        }else{
            document.getElementById("profileMsg").innerText = data.msg;
            document.getElementById("profileMsg").style.color = "#E74C3C";
        }
    }catch(e){
        console.error("修改昵称失败:", e);
        document.getElementById("profileMsg").innerText = "修改昵称失败";
        document.getElementById("profileMsg").style.color = "#E74C3C";
    }
}

async function changePassword(){
    const oldPwd = document.getElementById("profileOldPwd").value.trim();
    const newPwd = document.getElementById("profileNewPwd").value.trim();
    if(!oldPwd || !newPwd){
        document.getElementById("profileMsg").innerText = "请填写原密码和新密码";
        document.getElementById("profileMsg").style.color = "#E74C3C";
        return;
    }
    if(newPwd.length < 6){
        document.getElementById("profileMsg").innerText = "新密码至少需要6个字符";
        document.getElementById("profileMsg").style.color = "#E74C3C";
        return;
    }
    try{
        const res = await fetch("/user/change_password", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({old_password: oldPwd, new_password: newPwd})
        });
        const data = await res.json();
        if(data.ok === 1){
            document.getElementById("profileMsg").innerText = "密码修改成功，请重新登录";
            document.getElementById("profileMsg").style.color = "#2ECC71";
            document.getElementById("profileOldPwd").value = "";
            document.getElementById("profileNewPwd").value = "";
            setTimeout(() => {
                closeModal('profileModal');
                logout();
            }, 1500);
        }else{
            document.getElementById("profileMsg").innerText = data.msg;
            document.getElementById("profileMsg").style.color = "#E74C3C";
        }
    }catch(e){
        console.error("修改密码失败:", e);
        document.getElementById("profileMsg").innerText = "修改密码失败";
        document.getElementById("profileMsg").style.color = "#E74C3C";
    }
}

let currentInboxTab = 'all';
let currentInboxPage = 1;
let currentInboxMsgId = null;

async function openInbox(){
    openModal("inboxModal");
    loadInboxList('all');
    checkInboxUnread();
}

async function checkInboxUnread(){
    try{
        const res = await fetch("/inbox/list", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({page: 1, page_size: 1})
        });
        const data = await res.json();
        if(data.ok === 1 && data.unread_count > 0){
            const badge = document.getElementById("inboxUnreadCount");
            if(badge){
                badge.style.display = "inline";
                badge.innerText = data.unread_count > 99 ? "99+" : data.unread_count;
            }
        }
    }catch(e){
        console.error("检查未读邮件失败:", e);
    }
}

async function loadInboxList(type){
    currentInboxTab = type;
    const listDom = document.getElementById("inboxList");
    listDom.innerHTML = '<div style="text-align:center;color:#888;padding:20px;">加载中...</div>';
    document.getElementById("inboxTabAll").style.background = type === 'all' ? '#9B59B6' : '#555';
    document.getElementById("inboxTabUnread").style.background = type === 'unread' ? '#9B59B6' : '#555';
    try{
        const res = await fetch("/inbox/list", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({page: 1, page_size: 50, unread: type === 'unread'})
        });
        const data = await res.json();
        if(data.ok === 1){
            if(data.messages.length === 0){
                listDom.innerHTML = '<div style="text-align:center;color:#888;padding:30px;">暂无邮件</div>';
                return;
            }
            let html = '';
            data.messages.forEach(msg => {
                const typeClass = getInboxTypeClass(msg.type);
                const typeName = getInboxTypeName(msg.type);
                const readStyle = msg.read ? 'opacity:0.6;' : 'font-weight:600;';
                html += `
                    <div style="padding:18px;margin-bottom:12px;background:#252540;border-radius:10px;cursor:pointer;${readStyle};transition:all 0.2s;" onclick="openInboxDetail(${msg.id})">
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                            <span style="color:#fff;font-size:15px;">${msg.title}</span>
                            <span style="${typeClass};padding:4px 10px;border-radius:5px;font-size:11px;font-weight:500;">${typeName}</span>
                        </div>
                        <div style="display:flex;justify-content:space-between;font-size:13px;color:#888;">
                            <span>${msg.created_at}</span>
                            ${msg.read ? '' : '<span style="color:#E74C3C;font-weight:500;">● 未读</span>'}
                        </div>
                    </div>
                `;
            });
            listDom.innerHTML = html;
            const badge = document.getElementById("inboxUnreadCount");
            if(badge && data.unread_count > 0){
                badge.style.display = "inline";
                badge.innerText = data.unread_count > 99 ? "99+" : data.unread_count;
            }else if(badge){
                badge.style.display = "none";
            }
        }else{
            listDom.innerHTML = '<div style="text-align:center;color:#E74C3C;padding:20px;">加载失败</div>';
        }
    }catch(e){
        console.error("加载邮件列表失败:", e);
        listDom.innerHTML = '<div style="text-align:center;color:#E74C3C;padding:20px;">加载失败</div>';
    }
}

function getInboxTypeClass(type){
    const classes = {
        'mute': 'background:#E74C3C;color:#fff;',
        'unmute': 'background:#2ECC71;color:#fff;',
        'warning': 'background:#F39C12;color:#fff;',
        'notice': 'background:#3498DB;color:#fff;',
        'broadcast': 'background:#9B59B6;color:#fff;',
        'system': 'background:#555;color:#fff;'
    };
    return classes[type] || 'background:#555;color:#fff;';
}

function getInboxTypeName(type){
    const names = {
        'mute': '禁言通知',
        'unmute': '解除禁言',
        'warning': '警告',
        'notice': '公告',
        'broadcast': '广播',
        'system': '系统通知'
    };
    return names[type] || '通知';
}

async function openInboxDetail(msgId){
    currentInboxMsgId = msgId;
    try{
        const res = await fetch("/inbox/detail", {
            method: "POST",
            headers:{"Content-Type": "application/json"},
            body: JSON.stringify({id: msgId})
        });
        const data = await res.json();
        if(data.ok === 1){
            const msg = data.message;
            document.getElementById("inboxDetailTitle").innerText = "📧 " + msg.title;
            document.getElementById("inboxDetailTime").innerText = msg.created_at;
            const typeTag = document.getElementById("inboxDetailType");
            typeTag.innerText = getInboxTypeName(msg.type);
            typeTag.style.cssText = getInboxTypeClass(msg.type) + 'border-radius:3px;padding:2px 8px;';
            document.getElementById("inboxDetailContent").innerText = msg.content;
            openModal("inboxDetailModal");
            loadInboxList(currentInboxTab);
        }else{
            alert(data.msg);
        }
    }catch(e){
        console.error("加载邮件详情失败:", e);
        alert("加载失败");
    }
}

async function deleteCurrentInbox(){
    if(!currentInboxMsgId) return;
    if(!confirm("确定要删除这封邮件吗？")) return;
    try{
        const res = await fetch("/inbox/delete", {
            method: "POST",
            headers:{"Content-Type": "application/json"},
            body: JSON.stringify({id: currentInboxMsgId})
        });
        const data = await res.json();
        if(data.ok === 1){
            alert("邮件已删除");
            closeModal('inboxDetailModal');
            loadInboxList(currentInboxTab);
        }else{
            alert(data.msg);
        }
    }catch(e){
        console.error("删除邮件失败:", e);
        alert("删除失败");
    }
}

async function markAllInboxRead(){
    try{
        const res = await fetch("/inbox/list", {
            method: "POST",
            headers:{"Content-Type": "application/json"},
            body: JSON.stringify({page: 1, page_size: 100})
        });
        const data = await res.json();
        if(data.ok === 1 && data.messages.length > 0){
            const unreadIds = data.messages.filter(m => !m.read).map(m => m.id);
            if(unreadIds.length > 0){
                await fetch("/inbox/mark_read", {
                    method: "POST",
                    headers:{"Content-Type": "application/json"},
                    body: JSON.stringify({ids: unreadIds})
                });
            }
            loadInboxList(currentInboxTab);
            const badge = document.getElementById("inboxUnreadCount");
            if(badge) badge.style.display = "none";
            alert("已将所有邮件标记为已读");
        }
    }catch(e){
        console.error("标记已读失败:", e);
    }
}

async function doRegister(){
    const nickname = document.getElementById("regId").value.trim();
    const pwd = document.getElementById("regPwd").value.trim();
    const email = document.getElementById("regEmail").value.trim();
    const code = document.getElementById("regCode").value.trim();
    if(!nickname || !pwd || !email || !code){
        document.getElementById("regMsg").innerText = "请填写完整所有信息";
        return;
    }
    const res = await fetch("/register",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({nickname,pwd,email,code})
    });
    const data = await res.json();
    if(data.ok === 1){
        document.getElementById("regSuccessNickname").innerText = data.nickname;
        document.getElementById("regSuccessEmail").innerText = data.email;
        closeModal('regModal');
        openModal("regSuccessModal");
    }else{
        document.getElementById("regMsg").innerText = data.msg;
    }
}

async function doLogin(){
    const id = document.getElementById("loginId").value.trim();
    const pwd = document.getElementById("loginPwd").value.trim();
    if(!id || !pwd){
        document.getElementById("loginMsg").innerText = "请填写邮箱和密码";
        return;
    }
    const res = await fetch("/login",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({id,pwd})
    });
    const data = await res.json();
    if(data.ok === 1){
        document.getElementById("loginModal").style.display = "none";
        if(data.nickname){
            localStorage.setItem('user_nickname', data.nickname);
        }
        alert("登录成功，已解锁全部互动功能");
        window.location.reload();
    }else{
        document.getElementById("loginMsg").innerText = data.msg;
    }
}

function openFeedbackModal(){
    openModal("feedbackModal");
    document.getElementById("feedbackMsg").innerText = "";
    if(!isLogin){
        document.getElementById("feedbackNicknameArea").style.display = "block";
    }else{
        document.getElementById("feedbackNicknameArea").style.display = "none";
    }
}

async function submitFeedback(){
    const type = document.getElementById("feedbackType").value;
    const content = document.getElementById("feedbackContent").value.trim();
    const email = document.getElementById("feedbackEmail").value.trim();
    const nickname = document.getElementById("feedbackNickname").value.trim();
    if(!content || content.length < 10){
        document.getElementById("feedbackMsg").innerText = "反馈内容至少需要10个字符";
        return;
    }
    try{
        const res = await fetch("/feedback/submit", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                type: type,
                content: content,
                email: email,
                nickname: nickname
            })
        });
        const data = await res.json();
        if(data.ok === 1){
            document.getElementById("feedbackMsg").innerText = data.msg;
            document.getElementById("feedbackMsg").style.color = "#2ECC71";
            document.getElementById("feedbackContent").value = "";
            document.getElementById("feedbackEmail").value = "";
            document.getElementById("feedbackNickname").value = "";
            setTimeout(() => {
                closeModal("feedbackModal");
            }, 2000);
        }else{
            document.getElementById("feedbackMsg").innerText = data.msg;
        }
    }catch(err){
        document.getElementById("feedbackMsg").innerText = "提交失败: " + err;
    }
}

async function logout(){
    await fetch("/logout",{method:"POST"});
    localStorage.removeItem('user_nickname');
    alert("已退出登录");
    window.location.reload(true);
}

let refreshScheduleTimer = null;

async function refreshSchedule(){
    const year = parseInt(document.getElementById("yearSel").value, 10);
    const month = parseInt(document.getElementById("monthSel").value, 10);
    try{
        const res = await fetch("/get_schedule",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({year,month})
        });
        const scheduleList = await res.json();
        renderSideBar(scheduleList);
        if(currentView === 'calendar'){
            renderCalendar(scheduleList, year, month);
        }else if(currentView === 'timeline'){
            renderTimeline(scheduleList, year, month);
        }else if(currentView === 'card'){
            renderCardGrid(scheduleList, year, month);
        }
    }catch(err){
        console.error("刷新失败:", err);
    }
}

function debouncedRefreshSchedule() {
    if (refreshScheduleTimer) {
        clearTimeout(refreshScheduleTimer);
    }
    refreshScheduleTimer = setTimeout(() => {
        refreshSchedule();
    }, 300);
}

let registerScrolledToBottom = false;

function checkRegisterScroll() {
    const content = document.getElementById("registerNoticeContent");
    if (!content) return;
    const scrollTop = content.scrollTop;
    const scrollHeight = content.scrollHeight - content.clientHeight;
    if (scrollHeight <= 0) {
        registerScrolledToBottom = true;
    } else if (scrollTop >= scrollHeight - 10) {
        registerScrolledToBottom = true;
    }
}

function checkRegisterNotice() {
    const checkbox = document.getElementById("agreeRegisterNotice");
    const btn = document.getElementById("registerAgreeBtn");
    if (checkbox.checked && registerScrolledToBottom) {
        btn.disabled = false;
    } else {
        btn.disabled = true;
        if (!registerScrolledToBottom) {
            checkbox.checked = false;
            alert("请先滑动阅读完全部内容！");
        }
    }
}

function agreeRegisterNotice() {
    if (!registerScrolledToBottom) {
        alert("请先滑动阅读完全部内容！");
        return;
    }
    const checkbox = document.getElementById("agreeRegisterNotice");
    if (!checkbox.checked) {
        alert("请先勾选同意条款！");
        return;
    }
    document.getElementById("registerNoticeModal").style.display = "none";
    openModal("regModal");
}

let applyOpScrolledToBottom = false;

function checkApplyOpScroll() {
    const content = document.getElementById("applyOpNoticeContent");
    if (!content) return;
    const scrollTop = content.scrollTop;
    const scrollHeight = content.scrollHeight - content.clientHeight;
    if (scrollHeight <= 0) {
        applyOpScrolledToBottom = true;
    } else if (scrollTop >= scrollHeight - 10) {
        applyOpScrolledToBottom = true;
    }
}

function checkApplyOpNotice() {
    const checkbox = document.getElementById("agreeApplyOpNotice");
    const btn = document.getElementById("applyOpAgreeBtn");
    if (checkbox.checked && applyOpScrolledToBottom) {
        btn.disabled = false;
    } else {
        btn.disabled = true;
        if (!applyOpScrolledToBottom) {
            checkbox.checked = false;
            alert("请先滑动阅读完全部内容！");
        }
    }
}

function agreeApplyOpNotice() {
    if (!applyOpScrolledToBottom) {
        alert("请先滑动阅读完全部内容！");
        return;
    }
    const checkbox = document.getElementById("agreeApplyOpNotice");
    if (!checkbox.checked) {
        alert("请先勾选同意条款！");
        return;
    }
    document.getElementById("applyOpNoticeModal").style.display = "none";
    openModal("applyOpModal");
}

function renderCalendar(list, year, month){
    const processedList = (list || []).map(item => ({
        ...item,
        year: year,
        month: month
    }));
    currentScheduleList = processedList;
    const body = document.getElementById("calendarBody");
    if(!body) return;
    const firstDay = new Date(year, month - 1, 1).getDay();
    const daysInMonth = new Date(year, month, 0).getDate();
    const daysMap = {};
    if(Array.isArray(processedList)){
        processedList.forEach(item => {
            if(!daysMap[item.day]) daysMap[item.day] = [];
            daysMap[item.day].push(item);
        });
    }
    const icons = {
        qq: '🐧',
        phone: '📞',
        wechat: '💬',
        other: '📌'
    };
    let html = "";
    let dayNum = 1;
    for(let week = 0; week < 6; week++){
        html += "<tr>";
        for(let d = 0; d < 7; d++){
            if((week === 0 && d < firstDay) || dayNum > daysInMonth){
                html += "<td></td>";
            }else{
                let eventHtml = "";
                if(daysMap[dayNum]){
                    daysMap[dayNum].forEach(event => {
                        let cls = "event-future";
                        if(event.status === "live") cls = "event-live";
                        if(event.status === "past") cls = "event-past";
                        let btnHtml = "";
                        if(currentRole === ROLE_ADMIN || currentRole === ROLE_SUPER_ADMIN){
                            btnHtml = `
                                <div class="event-btns">
                                    <button class="edit" onclick="openEditModal(${event.id}); event.stopPropagation();">修改</button>
                                    <button class="del" onclick="delSchedule(${event.id}); event.stopPropagation();">删除</button>
                                </div>
                            `;
                        } else if((currentRole === ROLE_OP || currentRole === ROLE_TRUSTED_OP) && event.created_by === currentUser){
                            btnHtml = `
                                <div class="event-btns">
                                    <button class="edit" onclick="openEditModal(${event.id}); event.stopPropagation();">修改</button>
                                    <button class="del" onclick="delSchedule(${event.id}); event.stopPropagation();">删除</button>
                                </div>
                            `;
                        }
                        let contentHtml = `<div>时段：${event.time}</div><div>服ID：${event.server_id}</div>`;
                        if(event.creator_nickname) contentHtml += `<div>👤 提交者：${event.creator_nickname}</div>`;
                        if(event.contact_value) {
                            const icon = icons[event.contact_type] || '';
                            contentHtml += `<div>${icon} ${event.contact_value}</div>`;
                        }
                        let reservationHint = "";
                        if(currentUser && event.status === "future") {
                            reservationHint = `<div style="font-size:10px;color:#42C9D8;margin-top:4px;">👉 点击预约</div>`;
                        }
                        eventHtml += `
                            <div class="event ${cls}" onclick="showScheduleDetail(${event.id})">
                                ${contentHtml}
                                ${reservationHint}
                                ${btnHtml}
                            </div>
                        `;
                    });
                }
                html += `<td><div class="day-num">${dayNum}</div>${eventHtml}</td>`;
                dayNum++;
            }
        }
        html += "</tr>";
    }
    body.innerHTML = html;
}

function renderTimeline(list, year, month){
    const processedList = (list || []).map(item => ({
        ...item,
        year: year,
        month: month
    }));
    currentScheduleList = processedList;
    const body = document.getElementById("timelineBody");
    if(!body) return;
    const daysMap = {};
    if(Array.isArray(processedList)){
        processedList.forEach(item => {
            if(!daysMap[item.day]) daysMap[item.day] = [];
            daysMap[item.day].push(item);
        });
    }
    const icons = {
        qq: '🐧',
        phone: '📞',
        wechat: '💬',
        other: '📌'
    };
    const sortedDays = Object.keys(daysMap).sort((a,b) => parseInt(a) - parseInt(b));
    if(sortedDays.length === 0){
        body.innerHTML = `
            <div class="empty-state">
                <div style="font-size:48px;margin-bottom:16px;">📅</div>
                <div style="font-size:18px;color:var(--text-secondary);">本月暂无档期安排</div>
                <div style="font-size:14px;color:var(--text-muted);margin-top:8px;">快来添加第一个档期吧！</div>
            </div>
        `;
        return;
    }
    let html = '<div class="timeline">';
    sortedDays.forEach(day => {
        html += `
            <div class="timeline-date">
                <div class="timeline-date-marker"></div>
                <div class="timeline-date-title">${year}年${month}月${day}日</div>
                <div class="timeline-items">
        `;
        daysMap[day].forEach(event => {
            let statusCls = event.status;
            let btnHtml = "";
            if(currentRole === ROLE_ADMIN || currentRole === ROLE_SUPER_ADMIN){
                btnHtml = `
                    <div class="timeline-item-btns">
                        <button class="edit" onclick="openEditModal(${event.id}); event.stopPropagation();">✏️</button>
                        <button class="del" onclick="delSchedule(${event.id}); event.stopPropagation();">🗑️</button>
                    </div>
                `;
            } else if((currentRole === ROLE_OP || currentRole === ROLE_TRUSTED_OP) && event.created_by === currentUser){
                btnHtml = `
                    <div class="timeline-item-btns">
                        <button class="edit" onclick="openEditModal(${event.id}); event.stopPropagation();">✏️</button>
                        <button class="del" onclick="delSchedule(${event.id}); event.stopPropagation();">🗑️</button>
                    </div>
                `;
            }
            let contactHtml = "";
            if(event.contact_value){
                const icon = icons[event.contact_type] || '';
                contactHtml = `<div class="timeline-item-contact">${icon} ${event.contact_value}</div>`;
            }
            html += `
                <div class="timeline-item ${statusCls}" onclick="showScheduleDetail(${event.id})">
                    <div class="timeline-item-header">
                        <div class="timeline-item-time">🕐 ${event.time}</div>
                        <span class="timeline-item-status ${statusCls}">${event.status === 'live' ? '直播中' : event.status === 'past' ? '已结束' : '待开始'}</span>
                    </div>
                    <div class="timeline-item-server">🎮 服务器ID：${event.server_id}</div>
                    <div class="timeline-item-creator">👤 ${event.creator_nickname || '匿名'}</div>
                    ${contactHtml}
                    ${btnHtml}
                </div>
            `;
        });
        html += '</div></div>';
    });
    html += '</div>';
    body.innerHTML = html;
}

function renderCardGrid(list, year, month){
    const processedList = (list || []).map(item => ({
        ...item,
        year: year,
        month: month
    }));
    currentScheduleList = processedList;
    const body = document.getElementById("cardBody");
    if(!body) return;
    const icons = {
        qq: '🐧',
        phone: '📞',
        wechat: '💬',
        other: '📌'
    };
    if(processedList.length === 0){
        body.innerHTML = `
            <div class="empty-state">
                <div style="font-size:48px;margin-bottom:16px;">🃏</div>
                <div style="font-size:18px;color:var(--text-secondary);">本月暂无档期安排</div>
                <div style="font-size:14px;color:var(--text-muted);margin-top:8px;">快来添加第一个档期吧！</div>
            </div>
        `;
        return;
    }
    let html = '<div class="card-grid">';
    processedList.forEach(event => {
        let statusCls = event.status;
        let contactHtml = "";
        if(event.contact_value){
            const icon = icons[event.contact_type] || '';
            contactHtml = `<div class="schedule-card-contact">${icon} ${event.contact_value}</div>`;
        }
        let btnHtml = "";
        if(currentRole === ROLE_ADMIN || currentRole === ROLE_SUPER_ADMIN){
            btnHtml = `
                <div class="schedule-card-btns">
                    <button class="edit" onclick="openEditModal(${event.id}); event.stopPropagation();">✏️</button>
                    <button class="del" onclick="delSchedule(${event.id}); event.stopPropagation();">🗑️</button>
                </div>
            `;
        } else if((currentRole === ROLE_OP || currentRole === ROLE_TRUSTED_OP) && event.created_by === currentUser){
            btnHtml = `
                <div class="schedule-card-btns">
                    <button class="edit" onclick="openEditModal(${event.id}); event.stopPropagation();">✏️</button>
                    <button class="del" onclick="delSchedule(${event.id}); event.stopPropagation();">🗑️</button>
                </div>
            `;
        }
        html += `
            <div class="schedule-card ${statusCls}" onclick="showScheduleDetail(${event.id})">
                <div class="schedule-card-header">
                    <div class="schedule-card-date">${event.day}</div>
                    <div class="schedule-card-month">${year}年${month}月</div>
                </div>
                <div class="schedule-card-body">
                    <div class="schedule-card-time">🕐 ${event.time}</div>
                    <div class="schedule-card-server">🎮 服务器ID：${event.server_id}</div>
                    <div class="schedule-card-creator">👤 ${event.creator_nickname || '匿名'}</div>
                    ${contactHtml}
                </div>
                <div class="schedule-card-footer">
                    <span class="schedule-card-status ${statusCls}">${event.status === 'live' ? '直播中' : event.status === 'past' ? '已结束' : '待开始'}</span>
                    ${btnHtml}
                </div>
            </div>
        `;
    });
    html += '</div>';
    body.innerHTML = html;
}

async function showScheduleDetail(scheduleId) {
    const event = currentScheduleList.find(s => s.id == scheduleId);
    if(!event) return;
    currentViewingScheduleId = scheduleId;
    const icons = {
        qq: '🐧',
        phone: '📞',
        wechat: '💬',
        other: '📌'
    };
    const displayYear = parseInt(document.getElementById("yearSel").value, 10);
    const displayMonth = parseInt(document.getElementById("monthSel").value, 10);
    let dateStr = `${displayYear}年${displayMonth}月${event.day}日`;
    if (event.type === 'long' && event.end_month) {
        dateStr += ` ~ ${event.end_month}月${event.end_day}日`;
        if (event.end_year && event.end_year !== displayYear) {
            dateStr = `${displayYear}年${displayMonth}月${event.day}日 ~ ${event.end_year}年${event.end_month}月${event.end_day}日`;
        }
    }
    let detailHtml = `<div class="detail-item"><strong>📅 日期：</strong> ${dateStr}</div>`;
    detailHtml += `<div class="detail-item"><strong>🕐 时段：</strong> ${event.time}</div>`;
    if (event.type === 'long') {
        detailHtml += `<div class="detail-item"><strong>🔄 开服类型：</strong> <span style="color:#42C9D8">长期开服</span></div>`;
    }
    detailHtml += `<div class="detail-item"><strong>🎮 服务器ID：</strong> ${event.server_id}</div>`;
    if(event.creator_nickname) {
        detailHtml += `<div class="detail-item"><strong>👤 提交者：</strong> ${event.creator_nickname}</div>`;
    }
    if(event.reservation_count !== undefined) {
        detailHtml += `<div class="detail-item"><strong>📝 预约人数：</strong> <span style="color:#42C9D8">${event.reservation_count}</span> 人</div>`;
    }
    if(event.contact_value) {
        const icon = icons[event.contact_type] || '';
        const contactTypeNames = {
            qq: 'QQ',
            phone: '电话',
            wechat: '微信',
            other: '联系方式'
        };
        const typeName = contactTypeNames[event.contact_type] || '联系方式';
        detailHtml += `
            <div class="detail-item">
                <strong>${icon} ${typeName}：</strong> 
                <span class="copyable-text" onclick="copyText('${event.contact_value}')">${event.contact_value}</span>
            </div>
        `;
    }
    if(event.ip) {
        detailHtml += `
            <div class="detail-item">
                <strong>🖥️ 服务器IP：</strong> 
                <span class="copyable-text" onclick="copyText('${event.ip}')">${event.ip}</span>
            </div>
        `;
    }
    
    // 管理员专用的服务器状态查询开关
    if(currentRole === ROLE_ADMIN || currentRole === ROLE_SUPER_ADMIN) {
        const mcStatusCheck = event.mc_status_check === undefined ? 1 : event.mc_status_check;
        detailHtml += `
            <div class="detail-item" style="background:rgba(52,152,219,0.1);padding:10px;border-radius:4px;border-left:3px solid #3498DB;">
                <strong>🔧 管理员设置：</strong>
                <div style="margin-top:8px;display:flex;align-items:center;gap:15px;">
                    <label style="cursor:pointer;display:flex;align-items:center;gap:5px;">
                        <input type="radio" name="mcStatusCheck_${scheduleId}" value="1" ${mcStatusCheck === 1 ? 'checked' : ''} onchange="toggleMcStatusCheck(${scheduleId}, 1)"> 
                        <span>开启状态查询</span>
                    </label>
                    <label style="cursor:pointer;display:flex;align-items:center;gap:5px;">
                        <input type="radio" name="mcStatusCheck_${scheduleId}" value="0" ${mcStatusCheck === 0 ? 'checked' : ''} onchange="toggleMcStatusCheck(${scheduleId}, 0)"> 
                        <span>关闭状态查询</span>
                    </label>
                </div>
            </div>
        `;
    }
    
    if(event.ip && (event.mc_status_check === undefined || event.mc_status_check === 1) && currentUser && currentUser !== "" && currentUser !== "None") {
        detailHtml += `
            <div class="detail-item">
                <button onclick="openServerStatusModal('${event.ip}', ${scheduleId}, event)" style="background:#3498DB;color:#fff;padding:6px 12px;border:none;border-radius:4px;cursor:pointer;font-size:12px;">
                    🖥️ 查询服务器状态
                </button>
            </div>
        `;
    }
    let canViewReservations = false;
    if(event.reservation_count > 0) {
        if(currentRole === ROLE_ADMIN || currentRole === ROLE_SUPER_ADMIN) {
            canViewReservations = true;
        } else if((currentRole === ROLE_OP || currentRole === ROLE_TRUSTED_OP) && event.created_by === currentUser) {
            canViewReservations = true;
        }
    }
    if(canViewReservations) {
        detailHtml += `<div class="detail-item"><button class="forum-btn" style="margin-top:8px" onclick="showReservationList(${scheduleId})">查看预约人员</button></div>`;
    }
    if(currentUser && event.status === "future") {
        detailHtml += `<div class="detail-item"><div id="reservationBtnArea"></div></div>`;
    }
    detailHtml += `
        <div class="detail-item" style="border-top:1px dashed #444;padding-top:15px;margin-top:10px">
            <strong>💬 档期评论</strong>
            <div class="forum-input-group" style="margin-top:10px">
                <textarea id="scheduleForumComment_${scheduleId}" placeholder="对这个档口说点什么..."></textarea>
            </div>
            <button class="forum-btn" onclick="createScheduleForumComment(${scheduleId})">发表评论</button>
            <div id="scheduleForumComments_${scheduleId}" style="margin-top:10px">
                <div class="empty-tip">加载中...</div>
            </div>
        </div>
    `;
    document.getElementById('scheduleDetail').innerHTML = detailHtml;
    if(currentUser && event.status === "future") {
        await checkAndShowReservationBtn(scheduleId);
    }
    loadScheduleForumComments(scheduleId);
}

async function checkAndShowReservationBtn(scheduleId) {
    try {
        const res = await fetch("/check_reservation", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({schedule_id: scheduleId})
        });
        const data = await res.json();
        const btnArea = document.getElementById("reservationBtnArea");
        if(!btnArea) return;
        if(data.ok === 1) {
            if(data.reserved) {
                btnArea.innerHTML = `
                    <button style="background:#E74C3C;color:#fff;padding:8px 16px;border:none;border-radius:4px;cursor:pointer;" 
                            onclick="toggleReservation('${scheduleId}')">
                        取消预约
                    </button>
                `;
            } else {
                btnArea.innerHTML = `
                    <button style="background:#2ECC71;color:#000;padding:8px 16px;border:none;border-radius:4px;cursor:pointer;" 
                            onclick="toggleReservation('${scheduleId}')">
                        预约
                    </button>
                `;
            }
        }
    } catch(e) {
        console.error(e);
    }
}

const SERVER_STATUS_COOLDOWN = 10 * 60 * 1000;
let currentServerStatusHost = '';
let currentServerStatusScheduleId = null;
let currentServerStatusEndDate = '';
let serverStatusRefreshTimer = null;

function openServerStatusModal(host, scheduleId, scheduleData) {
    currentServerStatusHost = host;
    currentServerStatusScheduleId = scheduleId;
    const today = new Date();
    let endDate = new Date(today);
    endDate.setDate(today.getDate() + 7);
    if(scheduleData) {
        if(scheduleData.type === 'long' && scheduleData.end_month) {
            const endYear = scheduleData.end_year || scheduleData.year;
            endDate = new Date(endYear, scheduleData.end_month - 1, scheduleData.end_day);
        }
    }
    currentServerStatusEndDate = endDate.toISOString().split('T')[0];
    document.getElementById("serverStatusModalHost").innerHTML = `服务器：<strong>${host}</strong>`;
    document.getElementById("serverStatusModalContent").innerHTML = '<div style="text-align:center;color:#888;padding:40px 0;">查询中...</div>';
    const toggleDiv = document.getElementById("serverStatusModalToggle");
    const toggleBtn = document.getElementById("scheduleToggleBtn");
    if(currentRole === ROLE_ADMIN || currentRole === ROLE_SUPER_ADMIN) {
        if(toggleDiv) {
            toggleDiv.style.display = "block";
            if(toggleBtn) {
                toggleBtn.innerText = "⏸️ 关闭档期";
                toggleBtn.style.background = "#e74c3c";
                toggleBtn.style.color = "#fff";
            }
        }
    } else {
        if(toggleDiv) toggleDiv.style.display = "none";
    }
    openModal("serverStatusModal");
    queryServerStatus();
}

let cacheCountdownTimer = null;
function startCacheCountdown(seconds) {
    if(cacheCountdownTimer) {
        clearInterval(cacheCountdownTimer);
    }
    let remaining = seconds;
    const updateCountdown = () => {
        const el = document.getElementById("cacheCountdown");
        if(!el) {
            clearInterval(cacheCountdownTimer);
            return;
        }
        if(remaining <= 0) {
            el.innerText = "(数据更新中...)";
            clearInterval(cacheCountdownTimer);
            return;
        }
        const minutes = Math.floor(remaining / 60);
        const secs = remaining % 60;
        el.innerText = `(${minutes}分${secs}秒后更新)`;
        remaining--;
    };
    updateCountdown();
    cacheCountdownTimer = setInterval(updateCountdown, 1000);
}

async function queryServerStatus() {
    const host = currentServerStatusHost;
    const scheduleId = currentServerStatusScheduleId;
    const endDate = currentServerStatusEndDate;
    const statusContent = document.getElementById("serverStatusModalContent");
    if(!statusContent || !host) return;
    try {
        const res = await fetch("/mc_server/status", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({host: host, end_date: endDate})
        });
        const data = await res.json();
        if(data.ok === 1) {
            const onlineHtml = `
                <div style="background:#1a1a2e;padding:12px;border-radius:8px;">
                    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                        <span style="width:10px;height:10px;background:#2ECC71;border-radius:50%;"></span>
                        <span style="color:#2ECC71;font-weight:bold;">在线</span>
                    </div>
                    <div style="font-size:13px;line-height:1.8;">
                        <div><strong style="color:#888;">版本：</strong>${data.version}</div>
                        <div><strong style="color:#888;">在线玩家：</strong><span style="color:#42C9D8;">${data.players_online}/${data.players_max}</span></div>
                        <div><strong style="color:#888;">延迟：</strong>${data.latency}ms</div>
                        <div><strong style="color:#888;">上次查询：</strong>${data.query_time} <span id="cacheCountdown" style="color:#f39c12;">(${Math.floor(data.cache_remaining/60)}分${data.cache_remaining%60}秒后更新)</span></div>
                        <div><strong style="color:#888;">检测截止：</strong><span style="color:#f39c12;">${endDate}</span></div>
                    </div>
                </div>
            `;
            statusContent.innerHTML = onlineHtml;
            startCacheCountdown(data.cache_remaining);
        } else {
            if(data.expired) {
                const expiredHtml = `
                    <div style="background:#1a1a2e;padding:12px;border-radius:8px;">
                        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                            <span style="width:10px;height:10px;background:#95a5a6;border-radius:50%;"></span>
                            <span style="color:#95a5a6;font-weight:bold;">已结束</span>
                        </div>
                        <div style="font-size:13px;color:#888;">${data.msg}</div>
                    </div>
                `;
                statusContent.innerHTML = expiredHtml;
                if(serverStatusRefreshTimer) {
                    clearInterval(serverStatusRefreshTimer);
                    serverStatusRefreshTimer = null;
                }
            } else {
                const offlineHtml = `
                    <div style="background:#1a1a2e;padding:12px;border-radius:8px;">
                        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                            <span style="width:10px;height:10px;background:#E74C3C;border-radius:50%;"></span>
                            <span style="color:#E74C3C;font-weight:bold;">离线</span>
                        </div>
                        <div style="font-size:13px;color:#888;">${data.msg}</div>
                        <div style="font-size:13px;color:#888;margin-top:5px;">上次查询：${data.query_time || '未知'} <span id="cacheCountdown" style="color:#f39c12;">(${Math.floor((data.cache_remaining||0)/60)}分${(data.cache_remaining||0)%60}秒后更新)</span></div>
                        <div style="font-size:12px;color:#f39c12;margin-top:5px;">检测截止：${endDate}</div>
                    </div>
                `;
                statusContent.innerHTML = offlineHtml;
                if(data.cache_remaining) startCacheCountdown(data.cache_remaining);
            }
        }
} catch(e) {
    console.error("查询服务器状态失败:", e);
    statusContent.innerHTML = '<div style="color:#E74C3C;text-align:center;padding:40px 0;">查询失败，请稍后重试</div>';
}
}

async function toggleSchedule() {
    const scheduleId = currentServerStatusScheduleId;
    const toggleBtn = document.getElementById("scheduleToggleBtn");
    if(!scheduleId || !toggleBtn) return;
    const isAdmin = currentRole === ROLE_ADMIN || currentRole === ROLE_SUPER_ADMIN;
    if(!isAdmin) return;
    toggleBtn.disabled = true;
    toggleBtn.innerText = "操作中...";
    try {
        const res = await fetch("/schedule/toggle", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({schedule_id: scheduleId})
        });
        const data = await res.json();
        if(data.ok === 1) {
            const btn = document.getElementById("scheduleToggleBtn");
            if(data.active_status === 1) {
                btn.innerText = "⏸️ 关闭档期";
                btn.style.background = "#e74c3c";
                btn.style.color = "#fff";
            } else {
                btn.innerText = "▶️ 开启档期";
                btn.style.background = "#2ecc71";
                btn.style.color = "#fff";
                setTimeout(() => {
                    closeModal('serverStatusModal');
                    refreshSchedule();
                }, 1000);
            }
        } else {
            alert(data.msg || '操作失败');
            const btn = document.getElementById("scheduleToggleBtn");
            btn.innerText = "⏸️ 关闭档期";
            btn.style.background = "#e74c3c";
        }
    } catch(e) {
        console.error("切换档期状态失败:", e);
        alert('操作失败，请稍后重试');
        const btn = document.getElementById("scheduleToggleBtn");
        btn.innerText = "⏸️ 关闭档期";
        btn.style.background = "#e74c3c";
    } finally {
        const btn = document.getElementById("scheduleToggleBtn");
        if(btn) btn.disabled = false;
    }
}

function closeServerStatusModal() {
    document.getElementById("serverStatusModal").style.display = "none";
    if(serverStatusRefreshTimer) {
        clearInterval(serverStatusRefreshTimer);
        serverStatusRefreshTimer = null;
    }
    if(cacheCountdownTimer) {
        clearInterval(cacheCountdownTimer);
        cacheCountdownTimer = null;
    }
    currentServerStatusHost = '';
    currentServerStatusScheduleId = null;
}

async function createReservation(scheduleId) {
    if(!currentUser) {
        alert("请先登录！");
        openLogin();
        return;
    }
    try {
        const res = await fetch("/create_reservation", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({schedule_id: scheduleId})
        });
        const data = await res.json();
        if(data.ok === 1) {
            alert(data.msg || "预约成功！");
            await checkAndShowReservationBtn(scheduleId);
            await loadMyReservations();
        } else {
            alert(data.msg || "预约失败！");
        }
    } catch(e) {
        console.error(e);
        alert("请求出错，请查看控制台");
    }
}

async function cancelReservation(scheduleId) {
    if(!confirm("确定要取消这个预约吗？")) return;
    try {
        const myResRes = await fetch("/get_my_reservations", {
            method: "POST",
            headers: {"Content-Type": "application/json"}
        });
        const myResData = await myResRes.json();
        if(myResData.ok === 1 && myResData.reservations) {
            const reservation = myResData.reservations.find(r => r.schedule_id == scheduleId);
            if(reservation) {
                const cancelRes = await fetch("/cancel_reservation", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({reservation_id: reservation.id})
                });
                const cancelData = await cancelRes.json();
                if(cancelData.ok === 1) {
                    alert(cancelData.msg || "已取消预约");
                    await checkAndShowReservationBtn(scheduleId);
                    await loadMyReservations();
                } else {
                    alert(cancelData.msg || "取消失败");
                }
            }
        }
    } catch(e) {
        console.error(e);
        alert("请求出错，请查看控制台");
    }
}

async function toggleReservation(scheduleId) {
    if(!currentUser) {
        alert("请先登录！");
        openLogin();
        return;
    }
    try {
        const checkRes = await fetch("/check_reservation", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({schedule_id: scheduleId})
        });
        const checkData = await checkRes.json();
        if(checkData.ok !== 1) {
            alert("检查预约状态失败");
            return;
        }
        if(checkData.reserved) {
            const myResRes = await fetch("/get_my_reservations", {
                method: "POST",
                headers: {"Content-Type": "application/json"}
            });
            const myResData = await myResRes.json();
            if(myResData.ok === 1 && myResData.reservations) {
                const reservation = myResData.reservations.find(r => r.schedule_id == scheduleId);
                if(reservation) {
                    const cancelRes = await fetch("/cancel_reservation", {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({reservation_id: reservation.id})
                    });
                    const cancelData = await cancelRes.json();
                    if(cancelData.ok === 1) {
                        alert("已取消预约");
                        await checkAndShowReservationBtn(scheduleId);
                        await loadMyReservations();
                    } else {
                        alert(cancelData.msg || "取消失败");
                    }
                }
            }
        } else {
            const res = await fetch("/create_reservation", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({schedule_id: scheduleId})
            });
            const data = await res.json();
            if(data.ok === 1) {
                alert("预约成功！");
                await checkAndShowReservationBtn(scheduleId);
                await loadMyReservations();
            } else {
                alert(data.msg || "预约失败！");
            }
        }
    } catch(e) {
        console.error(e);
        alert("请求出错，请查看控制台");
    }
}

async function loadMyReservations() {
    const myResDom = document.getElementById("myReservations");
    if(!currentUser) {
        myResDom.innerHTML = '<div class="empty-tip">请先登录</div>';
        return;
    }
    try {
        const res = await fetch("/get_my_reservations", {
            method: "POST",
            headers: {"Content-Type": "application/json"}
        });
        const data = await res.json();
        if(data.ok === 1 && data.reservations && data.reservations.length > 0) {
            let html = "";
            data.reservations.forEach(item => {
                const reminderText = item.reminder_sent ? "（提醒已发送）" : "（提醒待发送）";
                html += `<div class="item">
                    ${item.month}月${item.day}日 ${item.time} | ${item.server_id} ${reminderText}
                </div>`;
            });
            myResDom.innerHTML = html;
        } else {
            myResDom.innerHTML = '<div class="empty-tip">暂无预约</div>';
        }
    } catch(e) {
        console.error(e);
        myResDom.innerHTML = '<div class="empty-tip">加载失败</div>';
    }
}

function copyText(text) {
    navigator.clipboard.writeText(text).then(() => {
        alert(`已复制：${text}`);
    }).catch(err => {
        const input = document.createElement('input');
        input.value = text;
        document.body.appendChild(input);
        input.select();
        document.execCommand('copy');
        document.body.removeChild(input);
        alert(`已复制：${text}`);
    });
}

function renderSideBar(list){
    const nextServerDom = document.getElementById("bookTip");
    const bookTipDom = document.getElementById("bookTip");
    const icons = {
        qq: '🐧',
        phone: '📞',
        wechat: '💬',
        other: '📌'
    };
    const futureList = list.filter(item => item.status === "future")
                            .sort((a,b) => a.day - b.day);
    const allList = [...list];
    if(futureList.length === 0){
        nextServerDom.innerHTML = '<div class="empty-tip">暂无即将开服的服务器</div>';
    }else{
        let html = "";
        futureList.forEach(item => {
            let contactStr = "";
            if(item.ip) contactStr += ` IP：${item.ip}`;
            if(item.contact_value) {
                const icon = icons[item.contact_type] || '';
                contactStr += ` ${icon}${item.contact_value}`;
            }
            let creatorStr = item.creator_nickname ? ` (👤${item.creator_nickname})` : "";
            html += `<div class="item">${item.day}日 ${item.time} | ${item.server_id}${contactStr}${creatorStr}</div>`;
        });
        nextServerDom.innerHTML = html;
    }
    if(allList.length === 0){
        bookTipDom.innerHTML = '<div class="empty-tip">暂无即将开服的服务器</div>';
    }else{
        const upcomingList = allList.filter(item => item.status === "future" || item.status === "live")
                                    .sort((a,b) => {
                                        if (a.month !== b.month) return a.month - b.month;
                                        if (a.day !== b.day) return a.day - b.day;
                                        const timeA = a.created_at || '';
                                        const timeB = b.created_at || '';
                                        return timeA.localeCompare(timeB);
                                    })
                                    .slice(0, 1);
        if(upcomingList.length === 0){
            bookTipDom.innerHTML = '<div class="empty-tip">暂无即将开服的服务器</div>';
        }else{
            let html = "";
            upcomingList.forEach(item => {
                let contactStr = "";
                if(item.ip) contactStr += ` IP：${item.ip}`;
                if(item.contact_value) {
                    const icon = icons[item.contact_type] || '';
                    contactStr += ` ${icon}${item.contact_value}`;
                }
                let creatorStr = item.creator_nickname ? ` (👤${item.creator_nickname})` : "";
                html += `<div class="item" style="cursor:pointer;" onclick="showScheduleDetail(${item.id})">${item.month}月${item.day}日 ${item.time} | ${item.server_id}${contactStr}${creatorStr}</div>`;
            });
            bookTipDom.innerHTML = html;
        }
    }
}

function setScheduleType(type){
    document.getElementById("scheduleType").value = type;
    const shortBtn = document.getElementById("scheduleTypeShort");
    const longBtn = document.getElementById("scheduleTypeLong");
    const endDateSection = document.getElementById("endDateSection");
    
    if(type === "short"){
        shortBtn.style.borderColor = "#3498DB";
        shortBtn.style.backgroundColor = "#3498DB";
        shortBtn.style.color = "#fff";
        longBtn.style.borderColor = "#555";
        longBtn.style.backgroundColor = "#333";
        longBtn.style.color = "#888";
        endDateSection.style.display = "none";
    } else {
        longBtn.style.borderColor = "#3498DB";
        longBtn.style.backgroundColor = "#3498DB";
        longBtn.style.color = "#fff";
        shortBtn.style.borderColor = "#555";
        shortBtn.style.backgroundColor = "#333";
        shortBtn.style.color = "#888";
        endDateSection.style.display = "block";
    }
}

async function submitAddSchedule(){
    const dateVal = document.getElementById("scheduleDate").value;
    const type = document.getElementById("scheduleType").value;
    const endDateVal = document.getElementById("scheduleEndDate").value;
    let time = document.getElementById("scheduleTime").value;
    const timeCustom = document.getElementById("scheduleTimeCustom").value.trim();
    const tagId = document.getElementById("scheduleTagSelect").value;
    const srvId = document.getElementById("serverId").value.trim();
    const ip = document.getElementById("serverIp").value.trim();
    const contactType = document.getElementById("contactType").value;
    const contactValue = document.getElementById("contactValue").value.trim();
    if(time === "其他" && timeCustom){
        time = timeCustom;
    }
    if(!dateVal){
        alert("请选择日期");
        return;
    }
    if(!time){
        alert("请选择或输入开服时段");
        return;
    }
    if(!tagId){
        alert("请选择标签");
        return;
    }
    if(!srvId){
        alert("请填写服务器ID");
        return;
    }
    if(!contactType || !contactValue){
        alert("请填写完整的联系方式");
        return;
    }
    const [y, m, d] = dateVal.split("-");
    const year = parseInt(y, 10);
    const month = parseInt(m, 10);
    const day = parseInt(d, 10);
    let endYear = null, endMonth = null, endDay = null;
    if (endDateVal) {
        const [ey, em, ed] = endDateVal.split("-");
        endYear = parseInt(ey, 10);
        endMonth = parseInt(em, 10);
        endDay = parseInt(ed, 10);
    }
    try{
        const res = await fetch("/add_schedule",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({
                year:year, month:month, day:day,
                type:type,
                end_year:endYear, end_month:endMonth, end_day:endDay,
                time:time, server_id:srvId, 
                ip:ip, contact_type:contactType, contact_value:contactValue,
                tags:[parseInt(tagId)]
            })
        });
        const data = await res.json();
        if(data.ok === 1){
            document.getElementById("addScheduleModal").style.display = "none";
            document.getElementById("scheduleDate").value = "";
            document.getElementById("scheduleType").value = "short";
            document.getElementById("scheduleEndDate").value = "";
            document.getElementById("scheduleTime").value = "";
            document.getElementById("scheduleTimeCustom").value = "";
            document.getElementById("scheduleTimeCustom").style.display = "none";
            document.getElementById("scheduleTagSelect").value = "";
            document.getElementById("serverId").value = "";
            document.getElementById("serverIp").value = "";
            document.getElementById("contactType").value = "";
            document.getElementById("contactValue").value = "";
            alert(data.msg || "新增档期成功");
            document.getElementById("yearSel").value = year;
            document.getElementById("monthSel").value = month;
            refreshSchedule();
        }else{
            alert(data.msg || "新增失败");
        }
    }catch(err){
        console.error("请求错误:", err);
        alert("请求出错，请查看控制台");
    }
}

async function delSchedule(id){
    if(!confirm("确定要删除该档期吗？")) return;
    await fetch("/del_schedule",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({id})
    });
    refreshSchedule();
}

async function toggleMcStatusCheck(scheduleId, value) {
    try {
        const res = await fetch("/toggle_mc_status_check", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                schedule_id: scheduleId,
                mc_status_check: value
            })
        });
        const data = await res.json();
        if(data.ok === 1) {
            alert(value === 1 ? "已开启服务器状态查询" : "已关闭服务器状态查询");
            refreshSchedule();
        } else {
            alert(data.msg || "操作失败");
        }
    } catch(err) {
        console.error("请求错误:", err);
        alert("请求出错，请查看控制台");
    }
}

async function openEditModal(id){
    event.stopPropagation();
    await loadEditScheduleTags();
    try{
        const res = await fetch("/get_schedule_detail",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({id})
        });
        const data = await res.json();
        if(data.ok === 1){
            const schedule = data.schedule;
            document.getElementById("editScheduleId").value = schedule.id;
            
            setEditScheduleType(schedule.type || 'short');
            
            document.getElementById("editScheduleDate").value = `${schedule.year}-${String(schedule.month).padStart(2,'0')}-${String(schedule.day).padStart(2,'0')}`;
            
            if(schedule.type === 'long' && schedule.end_month){
                const endYear = schedule.end_year || schedule.year;
                document.getElementById("editScheduleEndDate").value = `${endYear}-${String(schedule.end_month).padStart(2,'0')}-${String(schedule.end_day).padStart(2,'0')}`;
            } else {
                document.getElementById("editScheduleEndDate").value = "";
            }
            
            const timeSelect = document.getElementById("editScheduleTime");
            const timeCustom = document.getElementById("editScheduleTimeCustom");
            const predefinedTimes = ["00:00-06:00","06:00-12:00","12:00-18:00","18:00-24:00","全天"];
            if(predefinedTimes.includes(schedule.time)){
                timeSelect.value = schedule.time;
                timeCustom.style.display = "none";
            } else {
                timeSelect.value = "其他";
                timeCustom.style.display = "block";
                timeCustom.value = schedule.time;
            }
            
            const mcStatusCheck = schedule.mc_status_check || 1;
            document.querySelector(`input[name="editMcStatusCheck"][value="${mcStatusCheck}"]`).checked = true;
            
            document.getElementById("editServerId").value = schedule.server_id;
            document.getElementById("editServerIp").value = schedule.ip;
            document.getElementById("editContactType").value = schedule.contact_type;
            document.getElementById("editContactValue").value = schedule.contact_value;
            if(schedule.tags && schedule.tags.length > 0){
                document.getElementById("editScheduleTagSelect").value = schedule.tags[0].id;
            }
            document.getElementById("editScheduleTime").onchange = function(){
                const customInput = document.getElementById("editScheduleTimeCustom");
                if(this.value === "其他"){
                    customInput.style.display = "block";
                    customInput.focus();
                } else {
                    customInput.style.display = "none";
                    customInput.value = "";
                }
            };
            openModal("editScheduleModal");
        }else{
            alert(data.msg || "获取档期详情失败");
        }
    }catch(err){
        console.error("请求错误:", err);
        alert("请求出错，请查看控制台");
    }
}

async function loadEditScheduleTags(){
    try {
        const res = await fetch("/get_tags", {
            method: "POST",
            headers: {"Content-Type": "application/json"}
        });
        const data = await res.json();
        const select = document.getElementById("editScheduleTagSelect");
        if(data.ok === 1 && data.data && data.data.length > 0) {
            let html = '<option value="">请选择标签</option>';
            data.data.forEach(tag => {
                html += `<option value="${tag.id}" style="color:${tag.color}">${tag.name}</option>`;
            });
            select.innerHTML = html;
        } else {
            select.innerHTML = '<option value="">暂无标签</option>';
        }
    } catch(e) {
        console.error("加载标签失败:", e);
        document.getElementById("editScheduleTagSelect").innerHTML = '<option value="">加载失败</option>';
    }
}

function setEditScheduleType(type){
    document.getElementById("editScheduleType").value = type;
    const shortBtn = document.getElementById("editScheduleTypeShort");
    const longBtn = document.getElementById("editScheduleTypeLong");
    const endDateSection = document.getElementById("editEndDateSection");
    
    if(type === "short"){
        shortBtn.style.borderColor = "#3498DB";
        shortBtn.style.backgroundColor = "#3498DB";
        shortBtn.style.color = "#fff";
        longBtn.style.borderColor = "#555";
        longBtn.style.backgroundColor = "#333";
        longBtn.style.color = "#888";
        endDateSection.style.display = "none";
    } else {
        longBtn.style.borderColor = "#3498DB";
        longBtn.style.backgroundColor = "#3498DB";
        longBtn.style.color = "#fff";
        shortBtn.style.borderColor = "#555";
        shortBtn.style.backgroundColor = "#333";
        shortBtn.style.color = "#888";
        endDateSection.style.display = "block";
    }
}

async function submitEditSchedule(){
    const id = parseInt(document.getElementById("editScheduleId").value);
    const dateVal = document.getElementById("editScheduleDate").value;
    const type = document.getElementById("editScheduleType").value;
    const endDateVal = document.getElementById("editScheduleEndDate").value;
    let time = document.getElementById("editScheduleTime").value;
    const timeCustom = document.getElementById("editScheduleTimeCustom").value.trim();
    const tagId = document.getElementById("editScheduleTagSelect").value;
    const srvId = document.getElementById("editServerId").value.trim();
    const ip = document.getElementById("editServerIp").value.trim();
    const contactType = document.getElementById("editContactType").value;
    const contactValue = document.getElementById("editContactValue").value.trim();
    if(time === "其他" && timeCustom){
        time = timeCustom;
    }
    if(!dateVal){
        alert("请选择日期");
        return;
    }
    if(!time){
        alert("请选择或输入开服时段");
        return;
    }
    if(!tagId){
        alert("请选择标签");
        return;
    }
    if(!srvId){
        alert("请填写服务器ID");
        return;
    }
    if(!contactType || !contactValue){
        alert("请填写完整的联系方式");
        return;
    }
    const [y, m, d] = dateVal.split("-");
    const year = parseInt(y, 10);
    const month = parseInt(m, 10);
    const day = parseInt(d, 10);
    let endYear = null, endMonth = null, endDay = null;
    if (endDateVal) {
        const [ey, em, ed] = endDateVal.split("-");
        endYear = parseInt(ey, 10);
        endMonth = parseInt(em, 10);
        endDay = parseInt(ed, 10);
    }
    try{
        const res = await fetch("/edit_schedule",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({
                id: id,
                year:year, month:month, day:day,
                type:type,
                end_year:endYear, end_month:endMonth, end_day:endDay,
                time:time, server_id:srvId, 
                ip:ip, contact_type:contactType, contact_value:contactValue,
                tags:[parseInt(tagId)]
            })
        });
        const data = await res.json();
        if(data.ok === 1){
            document.getElementById("editScheduleModal").style.display = "none";
            alert("修改档期成功");
            document.getElementById("yearSel").value = year;
            document.getElementById("monthSel").value = month;
            refreshSchedule();
        }else{
            alert(data.msg || "修改失败");
        }
    }catch(err){
        console.error("请求错误:", err);
        alert("请求出错，请查看控制台");
    }
}

async function checkApplyStatus(){
    if(!currentUser || currentUser === "" || currentUser === "None"){
        currentApplyStatus = -1;
        return;
    }
    try{
        const res = await fetch("/check_op_apply", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({})
        });
        const data = await res.json();
        if(data.ok === 1){
            currentApplyStatus = data.status;
        }else{
            currentApplyStatus = -1;
        }
    }catch(e){
        console.error("获取申请状态失败:", e);
        currentApplyStatus = -1;
    }
}

async function submitApplyOp(){
    const serverIp = document.getElementById("applyServerIp").value.trim();
    const contact = document.getElementById("applyContact").value.trim();
    
    if(!serverIp){
        alert("请填写服务器IP地址");
        return;
    }
    
    try{
        const res = await fetch("/apply_op", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({server_ip: serverIp, contact: contact})
        });
        const data = await res.json();
        
        if(data.ok === 1){
            alert(data.msg);
            closeModal("applyOpModal");
            currentApplyStatus = 0;
            refreshRoleBtn();
        }else{
            alert(data.msg);
        }
    }catch(e){
        console.error("申请失败:", e);
        alert("申请失败，请稍后重试");
    }
}

function openApplyOpModal(){
    applyOpScrolledToBottom = false;
    const checkbox = document.getElementById("agreeApplyOpNotice");
    const btn = document.getElementById("applyOpAgreeBtn");
    const content = document.getElementById("applyOpNoticeContent");
    if(checkbox) checkbox.checked = false;
    if(btn) btn.disabled = true;
    if(content) content.scrollTop = 0;
    openModal("applyOpNoticeModal");
}

function renderComments(comments, isMainForum) {
    let html = '';
    comments.forEach(comment => {
        let deleteButtonHtml = '';
        if(currentRole === ROLE_ADMIN || currentRole === ROLE_SUPER_ADMIN) {
            deleteButtonHtml = `
                <button class="forum-btn" style="background:#E74C3C; color:#fff; font-size:10px; padding:2px 5px; margin-left:10px;"
                        onclick="deleteComment(${comment.id}, ${isMainForum})">删除</button>
            `;
        }
        html += `
            <div class="forum-post">
                <div class="forum-post-meta">👤 ${comment.nickname || '匿名用户'} | ${comment.created_at} ${deleteButtonHtml}</div>
                <div class="forum-post-content">${comment.content}</div>
            </div>
        `;
    });
    return html;
}

async function deleteComment(commentId, isMainForum) {
    if (!confirm("确定要删除这条评论吗？")) return;
    let url = isMainForum ? "/forum/delete_comment" : "/schedule_forum/delete_comment";
    try {
        const res = await fetch(url, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({comment_id: commentId})
        });
        const data = await res.json();
        if (data.ok === 1) {
            alert(data.msg || "删除成功！");
            if (isMainForum) {
                loadMainForumComments();
            } else {
                loadScheduleForumComments(currentViewingScheduleId);
            }
        } else {
            alert(data.msg || "删除失败！");
        }
    } catch(e) {
        console.error(e);
        alert("请求出错，请查看控制台");
    }
}

async function loadMainForumComments() {
    try {
        const res = await fetch("/forum/get_comments", {
            method: "POST",
            headers: {"Content-Type": "application/json"}
        });
        const data = await res.json();
        const commentsDom = document.getElementById("mainForumComments");
        if (commentsDom && data.ok === 1 && data.comments) {
            commentsDom.innerHTML = renderComments(data.comments, true);
        } else if (commentsDom) {
            commentsDom.innerHTML = '<div class="empty-tip">加载失败</div>';
        }
    } catch(e) {
        console.error(e);
        const commentsDom = document.getElementById("mainForumComments");
        if (commentsDom) {
            commentsDom.innerHTML = '<div class="empty-tip">加载失败</div>';
        }
    }
}

async function createMainForumComment() {
    if (!currentUser) {
        alert("请先登录！");
        openLogin();
        return;
    }
    const content = document.getElementById("mainForumComment").value.trim();
    if (!content) {
        alert("请填写评论内容！");
        return;
    }
    try {
        const res = await fetch("/forum/create_comment", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({content: content})
        });
        const data = await res.json();
        if (data.ok === 1) {
            document.getElementById("mainForumComment").value = "";
            loadMainForumComments();
        } else {
            alert(data.msg || "发表失败！");
        }
    } catch(e) {
        console.error(e);
        alert("请求出错，请查看控制台");
    }
}

async function loadScheduleForumComments(scheduleId) {
    try {
        const res = await fetch("/schedule_forum/get_comments", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({schedule_id: scheduleId})
        });
        const data = await res.json();
        const commentsDom = document.getElementById(`scheduleForumComments_${scheduleId}`);
        if (commentsDom && data.ok === 1 && data.comments) {
            commentsDom.innerHTML = renderComments(data.comments, false);
        } else if (commentsDom) {
            commentsDom.innerHTML = '<div class="empty-tip">加载失败</div>';
        }
    } catch(e) {
        console.error(e);
        const commentsDom = document.getElementById(`scheduleForumComments_${scheduleId}`);
        if (commentsDom) {
            commentsDom.innerHTML = '<div class="empty-tip">加载失败</div>';
        }
    }
}

async function createScheduleForumComment(scheduleId) {
    if (!currentUser) {
        alert("请先登录！");
        openLogin();
        return;
    }
    const content = document.getElementById(`scheduleForumComment_${scheduleId}`).value.trim();
    if (!content) {
        alert("请填写评论内容！");
        return;
    }
    try {
        const res = await fetch("/schedule_forum/create_comment", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({schedule_id: scheduleId, content: content})
        });
        const data = await res.json();
        if (data.ok === 1) {
            document.getElementById(`scheduleForumComment_${scheduleId}`).value = "";
            loadScheduleForumComments(scheduleId);
        } else {
            alert(data.msg || "发表失败！");
        }
    } catch(e) {
        console.error(e);
        alert("请求出错，请查看控制台");
    }
}

async function createScheduleForumReply(postId, scheduleId) {
    if(!currentUser) {
        alert("请先登录！");
        openLogin();
        return;
    }
    const replyInput = document.getElementById(`replyInput_${postId}`);
    const content = replyInput.value.trim();
    if(!content) {
        alert("请填写回复内容！");
        return;
    }
    try {
        const res = await fetch("/schedule_forum/create_reply", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({post_id: postId, content: content})
        });
        const data = await res.json();
        if(data.ok === 1) {
            alert("回复成功！");
            replyInput.value = "";
            loadScheduleForumComments(scheduleId);
        } else {
            alert(data.msg || "回复失败！");
        }
    } catch(e) {
        console.error(e);
        alert("请求出错，请查看控制台");
    }
}

let reservationListData = [];
let currentReservationPage = 1;
const reservationPageSize = 5;

async function showReservationList(scheduleId) {
    try {
        const res = await fetch("/get_schedule_reservations", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({schedule_id: scheduleId})
        });
        const data = await res.json();
        const contentEl = document.getElementById('reservationListContent');
        if(data.ok === 1 && data.reservations && data.reservations.length > 0) {
            reservationListData = data.reservations;
            currentReservationPage = 1;
            renderReservationList();
        } else {
            contentEl.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">👥</div>
                    <div class="empty-text">暂无预约人员</div>
                </div>
            `;
        }
        openModal("reservationListModal");
    } catch(e) {
        console.error(e);
        alert("请求出错，请查看控制台");
    }
}

function renderReservationList() {
    const contentEl = document.getElementById('reservationListContent');
    const totalPages = Math.ceil(reservationListData.length / reservationPageSize);
    const start = (currentReservationPage - 1) * reservationPageSize;
    const end = start + reservationPageSize;
    const pageData = reservationListData.slice(start, end);
    let listHtml = `
        <div class="reservation-list-header">
            <span class="reservation-count">共 ${reservationListData.length} 人预约</span>
            <span style="color:#888;font-size:12px;">第 ${currentReservationPage}/${totalPages} 页</span>
        </div>
        <div class="reservation-list">
    `;
    pageData.forEach((item, index) => {
        const globalIndex = start + index;
        listHtml += `
            <div class="reservation-item">
                <div class="reservation-rank">${globalIndex + 1}</div>
                <div class="reservation-info">
                    <div class="reservation-user">${item.nickname || item.user_id}</div>
                    ${item.email ? `<div class="reservation-email">${item.email}</div>` : ''}
                    <div class="reservation-time">${item.created_at}</div>
                </div>
            </div>
        `;
    });
    listHtml += '</div>';
    if(totalPages > 1) {
        listHtml += `
            <div class="reservation-pagination">
                <button class="page-btn" onclick="changeReservationPage(${currentReservationPage - 1})" ${currentReservationPage <= 1 ? 'disabled' : ''}>上一页</button>
                ${Array.from({length: totalPages}, (_, i) => 
                    `<button class="page-btn ${currentReservationPage === i + 1 ? 'active' : ''}" onclick="changeReservationPage(${i + 1})">${i + 1}</button>`
                ).join('')}
                <button class="page-btn" onclick="changeReservationPage(${currentReservationPage + 1})" ${currentReservationPage >= totalPages ? 'disabled' : ''}>下一页</button>
            </div>
        `;
    }
    contentEl.innerHTML = listHtml;
}

function changeReservationPage(page) {
    const totalPages = Math.ceil(reservationListData.length / reservationPageSize);
    if(page >= 1 && page <= totalPages && page !== currentReservationPage) {
        currentReservationPage = page;
        renderReservationList();
    }
}