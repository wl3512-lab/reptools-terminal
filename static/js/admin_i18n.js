/* Admin i18n — English ⟷ Mandarin. Selection persists in localStorage. */
(function () {
    var STORAGE_KEY = 'admin_lang';
    var current = localStorage.getItem(STORAGE_KEY) || 'en';

    var STRINGS = {
        en: {
            // Sidebar
            sb_manage: 'Manage',
            sb_dashboard: 'Dashboard',
            sb_products: 'Products',
            sb_analytics: 'Analytics',
            sb_tools: 'Tools',
            sb_backup: 'Download Backup',
            sb_view: 'View Site',
            sb_logout: 'Logout',
            sb_admin_badge: 'Admin',

            // Topbar / common
            tb_overview: 'Overview',
            tb_catalog: 'Catalog',
            tb_insights: 'Insights',
            tb_add_product: '+ Add product',
            tb_view_site: 'View site →',

            // Dashboard
            dash_products: 'Products',
            dash_clicks_30d: 'Clicks · 30d',
            dash_signups_30d: 'Signups · 30d',
            dash_daily_avg: 'Daily Avg',
            dash_per_day: 'clicks per day',
            dash_quick: 'Quick actions',
            dash_quick_sub: 'Common tasks',
            qa_import: 'Import products',
            qa_import_sub: 'Scrape link or paste JSON',
            qa_pin: 'Pin & reorder',
            qa_pin_sub: 'Curate the shop layout',
            qa_analytics: 'Analytics',
            qa_analytics_sub: 'Clicks, signups, top products',
            qa_backup: 'Backup DB',
            qa_backup_sub: 'Download full database',
            top_products: 'Top products · 30d',
            view_all: 'View all →',
            no_clicks: 'No clicks tracked yet',
            categories: 'Categories',
            recent: 'Recently updated',
            manage_all: 'Manage all →',
            no_products: 'No products yet',

            // Products page
            cat_help: 'Tip: Click ⭐ to pin a product to the top. Check rows to bulk-move them between categories or delete. In Reorder Mode, drag rows to set the exact order shown on /shop.',
            select_all: 'Select all',
            reorder_mode: 'Reorder mode',
            reorder_help_strong: 'Reorder mode:',
            reorder_help_rest: 'filter to one category first, drag rows, then save.',
            save_order: 'Save order',
            cancel: 'Cancel',
            move_to: 'Move to category…',
            move: 'Move',
            pin: '⭐ Pin',
            unpin: 'Unpin',
            delete: 'Delete',
            clear: 'Clear',
            search_placeholder: 'Search name, seller, tags…',
            all_categories: 'All categories',
            all_products_filter: 'All products',
            pinned_only: '⭐ Pinned only',
            not_pinned: 'Not pinned',
            th_name: 'Name',
            th_category: 'Category',
            th_price: 'Price',
            th_seller: 'Seller',
            th_actions: 'Actions',
            empty_table: 'No products yet. Use the Add Products panel above.',
            per_page: 'per page',

            // Add panel
            add_products: 'Add products',
            add_sub: 'Scrape · Manual · Bulk · Categories',
            tab_scrape: 'Scrape link',
            tab_manual: 'Add manually',
            tab_bulk: 'Bulk JSON',
            tab_categories: 'Categories',

            // Scrape
            scrape_help: 'Paste a Weidian / Taobao / 1688 link and every variant (colorway, size, style) will be scraped with image and price.',
            scrape_link_label: 'Product link *',
            scrape_category: 'Category',
            scrape_btn: 'Scrape',
            scrape_loading: 'Scraping… this may take a few seconds.',
            import_selected: 'Import selected',

            // Manual
            manual_name: 'Product name *',
            manual_category: 'Category',
            manual_price: 'Price (USD)',
            manual_retail: 'Retail price',
            manual_url: 'Product URL',
            manual_image: 'Image URL',
            manual_seller: 'Seller',
            manual_batch: 'Batch',
            add_product_btn: '+ Add product',

            // Bulk
            bulk_help_strong: 'name, price, url, image, category',
            upload: 'Upload',

            // Categories
            cat_slug: 'Slug *',
            cat_name: 'Display name *',
            cat_icon: 'Icon (emoji)',
            cat_order: 'Sort order',
            add_category_btn: '+ Add category',

            // Edit modal
            edit_product: 'Edit product',
            save_changes: 'Save changes',

            // Analytics
            an_total_clicks: 'Total Clicks',
            an_unique: 'Unique Visitors',
            an_signup_clicks: 'Signup Clicks',
            an_daily_avg: 'Daily Avg',
            an_per_day: 'clicks per day',
            an_daily_activity: 'Daily activity',
            an_no_traffic: 'No traffic yet for this period',
            an_top_products: 'Top products',
            an_by_clicks: 'by clicks',
            an_no_product_clicks: 'No product clicks yet',
            an_top_categories: 'Top categories',
            an_no_cat_clicks: 'No category clicks yet',
            an_top_pages: 'Top pages',
            an_by_views: 'by views',
            an_no_views: 'No page views yet',
            an_types: 'Interaction types',
            an_breakdown: 'click breakdown',
            an_no_interactions: 'No interactions tracked yet',

            // View modes
            view_pro_title: 'Pro',
            view_pro_desc: 'Dense tables · power user',
            view_comfort_title: 'Comfort',
            view_comfort_desc: 'Spacious cards · easier to read',
            view_exec_title: 'Executive',
            view_exec_desc: 'KPI-first · charts & trends',

            // Extra labels
            edit: 'Edit',
            del: 'Del',
            tags_label: 'Tags',
            footer_label: 'v1.0 · {agent}',

            // Stat-delta dynamic strings
            dash_pinned_cats: '{pinned} pinned · {cats} categories',
            dash_unique: '{n} unique visitors',
            dash_conv: '{pct}% of total clicks',
            an_avg_per_visitor: '{n} avg clicks/visitor',
            an_conv: '{pct}% conversion',
            an_with_traffic: '{n} days with traffic',

            // Analytics breakdown tab
            export_csv: 'Export CSV',
            th_product: 'Product',
            th_clicks: 'Clicks',
            th_share: 'Share',
            th_page: 'Page',
            th_views: 'Views',
            th_type: 'Type',

            // Analytics range pills
            rng_hour: 'Last hour',
            rng_today: 'Today',
            rng_24h: '24h',
            rng_7d: '7d',
            rng_30d: '30d',
            rng_90d: '90d',
            rng_mtd: 'MTD',
            rng_ytd: 'YTD',
            rng_1y: '1 year',
            rng_from: 'From',
            rng_to: 'to',
            rng_apply: 'Apply',
            rng_bucket_hour: 'hourly',
            rng_bucket_day: 'daily',
            rng_bucket_week: 'weekly',
            rng_bucket_month: 'monthly',
            an_hourly_avg: 'Hourly Avg',
            an_per_hour: 'clicks per hour',

            // Login
            login_signin: 'Sign in',
            login_restricted: 'Restricted access',
            login_password: 'Password',
            login_button: 'Sign In',
            login_back: '← Back to site',
            login_badge: 'Admin Panel',

            // Dynamic strings (used from JS via t())
            page_n_of_m: 'Page {n} of {m}',
            n_selected: '{n} selected',
            n_products: '{n} products',
            n_of_m_products: '{n} of {m} products',
            n_shown_of_total: '{n} shown · {m} total',
            n_total: '{n} total',
            product_added: 'Product added',
            product_updated: 'Product updated',
            product_deleted: 'Product deleted',
            n_deleted: 'Deleted {n} products',
            n_uploaded: '{n} products uploaded',
            n_imported: '{n} products imported',
            update_failed: 'Update failed',
            failed: 'Failed',
            invalid_json: 'Invalid JSON',
            must_be_array: 'Must be a JSON array',
            slug_name_required: 'Slug and name required',
            category_added: 'Category added',
            pinned_to_top: 'Pinned to top',
            unpinned: 'Unpinned',
            n_pinned: 'Pinned {n} products',
            n_unpinned: 'Unpinned {n} products',
            no_products_selected: 'No products selected',
            pick_category_first: 'Pick a category first',
            move_confirm: 'Move {n} products to "{cat}"?',
            moved_to: 'Moved {n} products to {cat}',
            delete_one_confirm: 'Delete this product?',
            delete_n_confirm: 'Delete {n} products? This cannot be undone.',
            saved_order_n: 'Saved order for {n} products',
            nothing_to_save: 'Nothing to save',
            reorder_filter_hint: 'Drag rows to reorder. Filter to a single category first.',
            enter_url: 'Enter a URL',
            scrape_failed: 'Scrape failed: {msg}',
            no_products_found: 'No products found',
            found_n_items: 'Found {n} items',
            n_variants: '{n} variants',
            scraped_products: 'Scraped products',
        },
        zh: {
            // Sidebar
            sb_manage: '管理',
            sb_dashboard: '仪表板',
            sb_products: '产品',
            sb_analytics: '数据分析',
            sb_tools: '工具',
            sb_backup: '下载备份',
            sb_view: '查看网站',
            sb_logout: '退出登录',
            sb_admin_badge: '管理员',

            // Topbar
            tb_overview: '概览',
            tb_catalog: '目录',
            tb_insights: '数据洞察',
            tb_add_product: '+ 添加产品',
            tb_view_site: '查看网站 →',

            // Dashboard
            dash_products: '产品',
            dash_clicks_30d: '点击数 · 30天',
            dash_signups_30d: '注册点击 · 30天',
            dash_daily_avg: '日均',
            dash_per_day: '每日点击',
            dash_quick: '快捷操作',
            dash_quick_sub: '常用任务',
            qa_import: '导入产品',
            qa_import_sub: '抓取链接或粘贴 JSON',
            qa_pin: '置顶与排序',
            qa_pin_sub: '管理商店布局',
            qa_analytics: '数据分析',
            qa_analytics_sub: '点击、注册、热门产品',
            qa_backup: '备份数据库',
            qa_backup_sub: '下载完整数据库',
            top_products: '热门产品 · 30天',
            view_all: '查看全部 →',
            no_clicks: '尚无点击数据',
            categories: '类别',
            recent: '最近更新',
            manage_all: '管理全部 →',
            no_products: '尚无产品',

            // Products page
            cat_help: '提示:点击 ⭐ 将产品置顶。勾选多行进行批量移动类别或删除。在排序模式中,拖动行设置 /shop 上的显示顺序。',
            select_all: '全选',
            reorder_mode: '排序模式',
            reorder_help_strong: '排序模式:',
            reorder_help_rest: '先筛选到一个类别,拖动行,然后保存。',
            save_order: '保存顺序',
            cancel: '取消',
            move_to: '移动到类别…',
            move: '移动',
            pin: '⭐ 置顶',
            unpin: '取消置顶',
            delete: '删除',
            clear: '清除',
            search_placeholder: '搜索名称、卖家、标签…',
            all_categories: '所有类别',
            all_products_filter: '所有产品',
            pinned_only: '⭐ 仅显示置顶',
            not_pinned: '未置顶',
            th_name: '名称',
            th_category: '类别',
            th_price: '价格',
            th_seller: '卖家',
            th_actions: '操作',
            empty_table: '尚无产品。请使用上方添加产品面板。',
            per_page: '每页',

            // Add panel
            add_products: '添加产品',
            add_sub: '抓取 · 手动 · 批量 · 类别',
            tab_scrape: '抓取链接',
            tab_manual: '手动添加',
            tab_bulk: '批量 JSON',
            tab_categories: '类别管理',

            // Scrape
            scrape_help: '粘贴微店 / 淘宝 / 1688 链接,所有变体(颜色、尺寸、款式)将连同图片和价格一同抓取。',
            scrape_link_label: '产品链接 *',
            scrape_category: '类别',
            scrape_btn: '抓取',
            scrape_loading: '正在抓取... 可能需要几秒钟。',
            import_selected: '导入所选',

            // Manual
            manual_name: '产品名称 *',
            manual_category: '类别',
            manual_price: '价格 (USD)',
            manual_retail: '零售价',
            manual_url: '产品 URL',
            manual_image: '图片 URL',
            manual_seller: '卖家',
            manual_batch: '批次',
            add_product_btn: '+ 添加产品',

            // Bulk
            bulk_help_strong: 'name, price, url, image, category',
            upload: '上传',

            // Categories
            cat_slug: 'Slug *',
            cat_name: '显示名称 *',
            cat_icon: '图标 (emoji)',
            cat_order: '排序',
            add_category_btn: '+ 添加类别',

            // Edit modal
            edit_product: '编辑产品',
            save_changes: '保存更改',

            // Analytics
            an_total_clicks: '总点击数',
            an_unique: '独立访客',
            an_signup_clicks: '注册点击',
            an_daily_avg: '日均',
            an_per_day: '每日点击',
            an_daily_activity: '每日活动',
            an_no_traffic: '此周期内尚无流量',
            an_top_products: '热门产品',
            an_by_clicks: '按点击数',
            an_no_product_clicks: '尚无产品点击',
            an_top_categories: '热门类别',
            an_no_cat_clicks: '尚无类别点击',
            an_top_pages: '热门页面',
            an_by_views: '按浏览数',
            an_no_views: '尚无页面浏览',
            an_types: '交互类型',
            an_breakdown: '点击分布',
            an_no_interactions: '尚无交互记录',

            // View modes
            view_pro_title: '专业',
            view_pro_desc: '密集表格 · 高级用户',
            view_comfort_title: '舒适',
            view_comfort_desc: '宽松卡片 · 易于阅读',
            view_exec_title: '执行',
            view_exec_desc: '指标优先 · 图表与趋势',

            // Extra labels
            edit: '编辑',
            del: '删除',
            tags_label: '标签',
            footer_label: 'v1.0 · {agent}',

            // Stat-delta dynamic strings
            dash_pinned_cats: '已置顶 {pinned} 个 · {cats} 个类别',
            dash_unique: '{n} 独立访客',
            dash_conv: '占总点击 {pct}%',
            an_avg_per_visitor: '每访客 {n} 次点击',
            an_conv: '{pct}% 转化率',
            an_with_traffic: '{n} 天有流量',

            // Analytics breakdown tab
            export_csv: '导出 CSV',
            th_product: '产品',
            th_clicks: '点击数',
            th_share: '占比',
            th_page: '页面',
            th_views: '浏览数',
            th_type: '类型',

            // Analytics range pills
            rng_hour: '最近一小时',
            rng_today: '今天',
            rng_24h: '24 小时',
            rng_7d: '7 天',
            rng_30d: '30 天',
            rng_90d: '90 天',
            rng_mtd: '本月',
            rng_ytd: '今年',
            rng_1y: '1 年',
            rng_from: '从',
            rng_to: '至',
            rng_apply: '应用',
            rng_bucket_hour: '按小时',
            rng_bucket_day: '按天',
            rng_bucket_week: '按周',
            rng_bucket_month: '按月',
            an_hourly_avg: '小时平均',
            an_per_hour: '每小时点击',

            // Login
            login_signin: '登录',
            login_restricted: '仅限授权访问',
            login_password: '密码',
            login_button: '登录',
            login_back: '← 返回网站',
            login_badge: '管理员后台',

            // Dynamic strings
            page_n_of_m: '第 {n} / {m} 页',
            n_selected: '已选 {n} 项',
            n_products: '{n} 个产品',
            n_of_m_products: '{n} / {m} 个产品',
            n_shown_of_total: '显示 {n} · 共 {m}',
            n_total: '共 {n}',
            product_added: '产品已添加',
            product_updated: '产品已更新',
            product_deleted: '产品已删除',
            n_deleted: '已删除 {n} 个产品',
            n_uploaded: '已上传 {n} 个产品',
            n_imported: '已导入 {n} 个产品',
            update_failed: '更新失败',
            failed: '失败',
            invalid_json: '无效的 JSON',
            must_be_array: '必须是 JSON 数组',
            slug_name_required: '需要 slug 和名称',
            category_added: '类别已添加',
            pinned_to_top: '已置顶',
            unpinned: '已取消置顶',
            n_pinned: '已置顶 {n} 个产品',
            n_unpinned: '已取消置顶 {n} 个产品',
            no_products_selected: '未选择产品',
            pick_category_first: '请先选择类别',
            move_confirm: '将 {n} 个产品移动到 "{cat}"?',
            moved_to: '已将 {n} 个产品移动到 {cat}',
            delete_one_confirm: '删除此产品?',
            delete_n_confirm: '删除 {n} 个产品?此操作无法撤销。',
            saved_order_n: '已保存 {n} 个产品的顺序',
            nothing_to_save: '没有要保存的内容',
            reorder_filter_hint: '拖动行进行排序。请先筛选到一个类别。',
            enter_url: '请输入 URL',
            scrape_failed: '抓取失败:{msg}',
            no_products_found: '未找到产品',
            found_n_items: '找到 {n} 个项目',
            n_variants: '{n} 个变体',
            scraped_products: '已抓取的产品',
        }
    };

    function interpolate(str, vars) {
        if (!vars) return str;
        return str.replace(/\{(\w+)\}/g, function (_, k) { return vars[k] != null ? vars[k] : ''; });
    }

    function parseVars(el) {
        var raw = el.dataset.i18nVars;
        if (!raw) return null;
        try { return JSON.parse(raw); } catch (e) { return null; }
    }

    function applyAll() {
        var dict = STRINGS[current] || STRINGS.en;
        document.querySelectorAll('[data-i18n]').forEach(function (el) {
            var key = el.dataset.i18n;
            var val = dict[key];
            if (val == null) return;
            el.textContent = interpolate(val, parseVars(el));
        });
        document.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
            var key = el.dataset.i18nPlaceholder;
            var val = dict[key];
            if (val == null) return;
            el.placeholder = interpolate(val, parseVars(el));
        });
        document.querySelectorAll('[data-i18n-aria]').forEach(function (el) {
            var key = el.dataset.i18nAria;
            var val = dict[key];
            if (val == null) return;
            el.setAttribute('aria-label', interpolate(val, parseVars(el)));
        });
        document.querySelectorAll('[data-lang-label]').forEach(function (el) {
            el.textContent = current === 'zh' ? '中文' : 'EN';
        });
        document.querySelectorAll('[data-lang-other]').forEach(function (el) {
            el.textContent = current === 'zh' ? 'EN' : '中文';
        });
        document.documentElement.lang = current;
    }

    // Set language explicitly.
    window.setAdminLang = function (lang) {
        if (!STRINGS[lang]) return;
        current = lang;
        localStorage.setItem(STORAGE_KEY, lang);
        applyAll();
        // Tell page-specific code (pagination text, bulk-select count, etc.)
        // to re-render their dynamic strings.
        try {
            document.dispatchEvent(new CustomEvent('admin-lang-changed', { detail: { lang: lang } }));
        } catch (e) { /* old browser */ }
    };

    // Simple toggle — flips between en and zh.
    window.toggleAdminLang = function () {
        window.setAdminLang(current === 'zh' ? 'en' : 'zh');
    };

    // Translation helper — usable from any admin JS for dynamic strings.
    //   t('n_products', { n: 42 })  →  '42 products' / '42 个产品'
    //   t('unknown_key')            →  'unknown_key' (falls back to key)
    window.t = function (key, vars) {
        var dict = STRINGS[current] || STRINGS.en;
        var s = dict[key];
        if (s == null) return key;
        return interpolate(s, vars);
    };

    // Current language code.
    window.getAdminLang = function () { return current; };

    // Apply once on load — immediately if DOM is already parsed, otherwise wait.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', applyAll);
    } else {
        applyAll();
    }
    window.refreshAdminI18n = applyAll;
})();
