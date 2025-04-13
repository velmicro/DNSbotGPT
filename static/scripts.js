function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const content = document.getElementById('content');

    sidebar.classList.toggle('collapsed');
    content.classList.toggle('collapsed');

    // Сохраняем состояние в localStorage
    const isCollapsed = sidebar.classList.contains('collapsed');
    localStorage.setItem('sidebarCollapsed', isCollapsed ? 'true' : 'false');
}

// Восстанавливаем состояние при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
    const sidebar = document.getElementById('sidebar');
    const content = document.getElementById('content');
    const savedState = localStorage.getItem('sidebarCollapsed');

    if (savedState === 'true') {
        sidebar.classList.add('collapsed');
        content.classList.add('collapsed');
    }
});
