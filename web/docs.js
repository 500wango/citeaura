const docsSidebar = document.querySelector('.docs-sidebar');
const sidebarToggle = document.querySelector('.docs-sidebar-toggle');
const setSidebarOpen = (open) => {
  docsSidebar?.classList.toggle('is-open', open);
  sidebarToggle?.setAttribute('aria-expanded', String(open));
};

sidebarToggle?.addEventListener('click', () => {
  setSidebarOpen(!docsSidebar?.classList.contains('is-open'));
});

const searchInput = document.getElementById('docs-search');
if (searchInput) {
  searchInput.addEventListener('input', (event) => {
    const query = event.target.value.toLowerCase().trim();
    if (query) setSidebarOpen(true);
    document.querySelectorAll('.docs-nav-link').forEach((link) => {
      link.style.display = link.textContent.toLowerCase().includes(query) ? 'flex' : 'none';
    });
  });
}

document.querySelectorAll('.docs-nav-link').forEach((link) => {
  link.addEventListener('click', () => {
    if (window.matchMedia('(max-width: 768px)').matches) setSidebarOpen(false);
  });
});

const observer = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (!entry.isIntersecting) return;
    const id = entry.target.getAttribute('id');
    document.querySelectorAll('.docs-nav-link, .docs-toc a').forEach((link) => {
      if (link.getAttribute('href') === `#${id}`) link.classList.add('is-active');
      else if (link.getAttribute('href')?.startsWith('#')) link.classList.remove('is-active');
    });
  });
}, { rootMargin: '-20% 0px -70% 0px' });

document.querySelectorAll('.docs-article section[id]').forEach((section) => observer.observe(section));
