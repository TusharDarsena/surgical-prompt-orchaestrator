<!DOCTYPE html>

<html class="light" lang="en"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<link href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@300;400;500;600;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script id="tailwind-config">
        tailwind.config = {
            darkMode: "class",
            theme: {
                extend: {
                    colors: {
                        "primary": "#ec5b13",
                        "background-light": "#f8f6f6",
                        "background-dark": "#221610",
                    },
                    fontFamily: {
                        "display": ["Public Sans"]
                    },
                    borderRadius: {"DEFAULT": "0.25rem", "lg": "0.5rem", "xl": "0.75rem", "full": "9999px"},
                },
            },
        }
    </script>
<style>
        body { font-family: 'Public Sans', sans-serif; }
        .custom-scrollbar::-webkit-scrollbar { width: 4px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: #ec5b1333; border-radius: 10px; }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover { background: #ec5b1366; }
    </style>
</head>
<body class="bg-background-light dark:bg-background-dark text-slate-900 dark:text-slate-100 font-display">
<div class="flex h-screen overflow-hidden">
<!-- Sidebar - Condensed -->
<aside class="w-64 border-r border-primary/10 flex flex-col bg-white dark:bg-background-dark/50">
<div class="p-4 border-b border-primary/10 flex items-center gap-2">
<div class="size-8 bg-primary rounded-lg flex items-center justify-center text-white">
<span class="material-symbols-outlined text-lg">edit_note</span>
</div>
<h2 class="font-bold text-sm tracking-tight">Streamlit Editor</h2>
</div>
<nav class="flex-1 p-2 space-y-1 overflow-y-auto custom-scrollbar">
<div class="flex items-center gap-3 px-3 py-1.5 rounded-lg bg-primary/10 text-primary">
<span class="material-symbols-outlined text-xl">folder</span>
<p class="text-xs font-semibold">Pro Workspace</p>
</div>
<a class="flex items-center gap-3 px-3 py-1.5 rounded-lg hover:bg-primary/5 transition-colors" href="#">
<span class="material-symbols-outlined text-xl text-slate-500">home</span>
<p class="text-xs font-medium">Home</p>
</a>
<a class="flex items-center gap-3 px-3 py-1.5 rounded-lg hover:bg-primary/5 transition-colors" href="#">
<span class="material-symbols-outlined text-xl text-slate-500">description</span>
<p class="text-xs font-medium">Drafts</p>
</a>
<a class="flex items-center gap-3 px-3 py-1.5 rounded-lg hover:bg-primary/5 transition-colors" href="#">
<span class="material-symbols-outlined text-xl text-slate-500">segment</span>
<p class="text-xs font-medium">Sections</p>
</a>
<a class="flex items-center gap-3 px-3 py-1.5 rounded-lg hover:bg-primary/5 transition-colors" href="#">
<span class="material-symbols-outlined text-xl text-slate-500">history</span>
<p class="text-xs font-medium">History</p>
</a>
<div class="pt-4 pb-2 px-3 text-[10px] uppercase font-bold text-slate-400">Settings</div>
<a class="flex items-center gap-3 px-3 py-1.5 rounded-lg hover:bg-primary/5 transition-colors" href="#">
<span class="material-symbols-outlined text-xl text-slate-500">settings</span>
<p class="text-xs font-medium">Configuration</p>
</a>
</nav>
<div class="p-3 border-t border-primary/10 flex items-center gap-3">
<div class="size-8 rounded-full bg-slate-200" data-alt="User profile avatar placeholder"></div>
<div class="flex-1 min-w-0">
<p class="text-[11px] font-bold truncate">Alex Editor</p>
<p class="text-[10px] text-slate-500 truncate">Pro Account</p>
</div>
</div>
</aside>
<!-- Main Content Area -->
<main class="flex-1 flex flex-col min-w-0 bg-background-light dark:bg-background-dark">
<!-- Header - Ultra Slim -->
<header class="h-12 border-b border-primary/10 flex items-center justify-between px-6 bg-white dark:bg-background-dark/80 backdrop-blur-sm sticky top-0 z-10">
<div class="flex items-center gap-4">
<h1 class="text-sm font-bold">Write a Section</h1>
<span class="px-2 py-0.5 rounded bg-primary/10 text-primary text-[10px] font-bold">DRAFT MODE</span>
</div>
<div class="flex items-center gap-2">
<button class="flex items-center gap-1.5 px-3 py-1 rounded-lg border border-primary/20 hover:bg-primary/5 text-xs font-medium transition-colors">
<span class="material-symbols-outlined text-sm">share</span>
<span>Share</span>
</button>
<button class="flex items-center gap-1.5 px-4 py-1 rounded-lg bg-primary text-white text-xs font-bold hover:brightness-110 transition-all shadow-sm shadow-primary/20">
<span class="material-symbols-outlined text-sm">save</span>
<span>Save Section</span>
</button>
</div>
</header>
<!-- Editor Viewport -->
<div class="flex-1 overflow-y-auto p-4 custom-scrollbar space-y-3">
<!-- Metrics Bar - Single Row, Tiny Cards -->
<div class="grid grid-cols-4 gap-3">
<div class="bg-white dark:bg-slate-800/50 p-2 rounded-lg border border-primary/10 flex items-center gap-3">
<div class="size-8 rounded bg-primary/10 text-primary flex items-center justify-center shrink-0">
<span class="material-symbols-outlined text-lg">article</span>
</div>
<div>
<p class="text-[10px] text-slate-500 font-medium leading-none mb-1">Words</p>
<p class="text-sm font-bold leading-none">452</p>
</div>
</div>
<div class="bg-white dark:bg-slate-800/50 p-2 rounded-lg border border-primary/10 flex items-center gap-3">
<div class="size-8 rounded bg-primary/10 text-primary flex items-center justify-center shrink-0">
<span class="material-symbols-outlined text-lg">schedule</span>
</div>
<div>
<p class="text-[10px] text-slate-500 font-medium leading-none mb-1">Time</p>
<p class="text-sm font-bold leading-none">2m 15s</p>
</div>
</div>
<div class="bg-white dark:bg-slate-800/50 p-2 rounded-lg border border-primary/10 flex items-center gap-3">
<div class="size-8 rounded bg-primary/10 text-primary flex items-center justify-center shrink-0">
<span class="material-symbols-outlined text-lg">link</span>
</div>
<div>
<p class="text-[10px] text-slate-500 font-medium leading-none mb-1">Sources</p>
<p class="text-sm font-bold leading-none">12</p>
</div>
</div>
<div class="bg-white dark:bg-slate-800/50 p-2 rounded-lg border border-primary/10 flex items-center gap-3">
<div class="size-8 rounded bg-primary/10 text-primary flex items-center justify-center shrink-0">
<span class="material-symbols-outlined text-lg">analytics</span>
</div>
<div>
<p class="text-[10px] text-slate-500 font-medium leading-none mb-1">Score</p>
<p class="text-sm font-bold leading-none">98%</p>
</div>
</div>
</div>
<div class="grid grid-cols-12 gap-3 items-start">
<!-- Left: Editor & Prompts (9 cols) -->
<div class="col-span-9 space-y-3">
<!-- Prompt Output Boxes - Side-by-Side -->
<div class="grid grid-cols-2 gap-3">
<div class="bg-white dark:bg-slate-800/50 rounded-lg border border-primary/10 flex flex-col">
<div class="px-3 py-1.5 border-b border-primary/5 flex items-center justify-between">
<span class="text-[11px] font-bold uppercase tracking-wider text-slate-400">Context Prompt</span>
<span class="material-symbols-outlined text-sm text-slate-400 cursor-pointer hover:text-primary transition-colors">content_copy</span>
</div>
<div class="p-2 min-h-[80px]">
<p class="text-xs text-slate-600 dark:text-slate-300 leading-relaxed italic">"Analyze the correlation between user retention and minimalist UI patterns within the SaaS sector for the 2024 fiscal year..."</p>
</div>
</div>
<div class="bg-white dark:bg-slate-800/50 rounded-lg border border-primary/10 flex flex-col">
<div class="px-3 py-1.5 border-b border-primary/5 flex items-center justify-between">
<span class="text-[11px] font-bold uppercase tracking-wider text-slate-400">Tone Guidance</span>
<span class="material-symbols-outlined text-sm text-slate-400 cursor-pointer hover:text-primary transition-colors">tune</span>
</div>
<div class="p-2 min-h-[80px]">
<p class="text-xs text-slate-600 dark:text-slate-300 leading-relaxed">Maintain a professional, data-driven narrative. Avoid superlative language. Focus on empirical evidence and structured observations.</p>
</div>
</div>
</div>
<!-- Draft Output Section -->
<div class="bg-white dark:bg-slate-800 rounded-xl border border-primary/20 shadow-sm">
<div class="px-4 py-2 border-b border-primary/10 flex items-center justify-between">
<span class="text-xs font-bold text-primary">Main Draft Editor</span>
<div class="flex gap-2">
<button class="size-6 flex items-center justify-center rounded hover:bg-slate-100 dark:hover:bg-slate-700">
<span class="material-symbols-outlined text-sm">format_bold</span>
</button>
<button class="size-6 flex items-center justify-center rounded hover:bg-slate-100 dark:hover:bg-slate-700">
<span class="material-symbols-outlined text-sm">format_italic</span>
</button>
<button class="size-6 flex items-center justify-center rounded hover:bg-slate-100 dark:hover:bg-slate-700">
<span class="material-symbols-outlined text-sm">link</span>
</button>
</div>
</div>
<textarea class="w-full p-4 text-sm bg-transparent border-none focus:ring-0 min-h-[300px] resize-none leading-relaxed" placeholder="Start writing your section here...">The transition towards "invisible interfaces" has marked a significant shift in SaaS product design. Our internal metrics suggest that users are 24% more likely to complete complex onboarding tasks when UI elements are contextually disclosed rather than persistent. 

This finding aligns with the 2024 industry report on cognitive load, which identifies that the average workspace professional interacts with over 14 distinct software tools daily. Reducing the visual noise of each tool becomes a competitive advantage. 

Specifically, in our latest sprint, the 'Pro' workspace toggle resulted in a measurable increase in session duration, suggesting that power users value the density and speed provided by a more condensed UI layout. Future iterations should focus on maintaining this high information density without sacrificing readability.</textarea>
</div>
<!-- Consistency Summary - Condensed -->
<div class="bg-slate-100 dark:bg-slate-800/30 p-3 rounded-lg border border-slate-200 dark:border-slate-700">
<h4 class="text-[11px] font-bold uppercase text-slate-400 mb-2 flex items-center gap-2">
<span class="material-symbols-outlined text-sm">spellcheck</span>
                            Consistency Summary
                        </h4>
<div class="flex flex-wrap gap-4">
<div class="flex items-center gap-2">
<span class="size-2 rounded-full bg-green-500"></span>
<span class="text-xs font-medium">Terminology: Uniform</span>
</div>
<div class="flex items-center gap-2">
<span class="size-2 rounded-full bg-green-500"></span>
<span class="text-xs font-medium">Tone: Professional</span>
</div>
<div class="flex items-center gap-2">
<span class="size-2 rounded-full bg-orange-400"></span>
<span class="text-xs font-medium">Readability: Level 12 (Target Level 10)</span>
</div>
</div>
</div>
</div>
<!-- Right: Sources (3 cols) -->
<div class="col-span-3 h-full">
<div class="bg-white dark:bg-slate-800/50 border border-primary/10 rounded-lg flex flex-col sticky top-16 max-h-[calc(100vh-120px)]">
<div class="px-3 py-2 border-b border-primary/5 flex items-center justify-between">
<h4 class="text-[11px] font-bold uppercase text-slate-400">Sources</h4>
<button class="text-primary text-[10px] font-bold hover:underline">Manage</button>
</div>
<div class="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-2">
<!-- Slim Source List Items -->
<div class="p-2 rounded hover:bg-primary/5 border border-transparent hover:border-primary/10 transition-all group cursor-pointer">
<div class="flex items-center gap-2 mb-1">
<span class="material-symbols-outlined text-xs text-primary">description</span>
<p class="text-[11px] font-bold truncate group-hover:text-primary">Q1 Market Trends.pdf</p>
</div>
<p class="text-[10px] text-slate-500 line-clamp-2">"User retention rates increased by 12% across platforms adopting minimalist..."</p>
</div>
<div class="p-2 rounded hover:bg-primary/5 border border-transparent hover:border-primary/10 transition-all group cursor-pointer">
<div class="flex items-center gap-2 mb-1">
<span class="material-symbols-outlined text-xs text-primary">link</span>
<p class="text-[11px] font-bold truncate group-hover:text-primary">UX Collective Article</p>
</div>
<p class="text-[10px] text-slate-500 line-clamp-2">Research on cognitive load and SaaS interaction patterns for power users.</p>
</div>
<div class="p-2 rounded hover:bg-primary/5 border border-transparent hover:border-primary/10 transition-all group cursor-pointer">
<div class="flex items-center gap-2 mb-1">
<span class="material-symbols-outlined text-xs text-primary">article</span>
<p class="text-[11px] font-bold truncate group-hover:text-primary">Internal Audit Findings</p>
</div>
<p class="text-[10px] text-slate-500 line-clamp-2">Comparison of session length between legacy and modern UI versions.</p>
</div>
<div class="p-2 rounded hover:bg-primary/5 border border-transparent hover:border-primary/10 transition-all group cursor-pointer">
<div class="flex items-center gap-2 mb-1">
<span class="material-symbols-outlined text-xs text-primary">description</span>
<p class="text-[11px] font-bold truncate group-hover:text-primary">User Survey Data.csv</p>
</div>
<p class="text-[10px] text-slate-500 line-clamp-2">Raw feedback scores from the 2024 Q3 usability testing cohort.</p>
</div>
<div class="p-2 rounded hover:bg-primary/5 border border-transparent hover:border-primary/10 transition-all group cursor-pointer">
<div class="flex items-center gap-2 mb-1">
<span class="material-symbols-outlined text-xs text-primary">description</span>
<p class="text-[11px] font-bold truncate group-hover:text-primary">Industry Benchmarks</p>
</div>
<p class="text-[10px] text-slate-500 line-clamp-2">Standard competitive analysis metrics for SaaS platforms.</p>
</div>
<!-- More sources would continue here -->
</div>
<div class="p-2 border-t border-primary/5">
<button class="w-full py-1.5 border border-dashed border-primary/30 rounded text-[10px] font-bold text-primary hover:bg-primary/5 flex items-center justify-center gap-1">
<span class="material-symbols-outlined text-sm">add</span> Add Source
                            </button>
</div>
</div>
</div>
</div>
</div>
<!-- Sticky Footer - Ultra Condensed Status -->
<footer class="h-8 border-t border-primary/10 flex items-center justify-between px-4 bg-white dark:bg-background-dark/95 text-[10px] text-slate-400">
<div class="flex items-center gap-4">
<span class="flex items-center gap-1"><span class="size-1.5 rounded-full bg-green-500"></span> Connected to Engine</span>
<span class="flex items-center gap-1"><span class="material-symbols-outlined text-[10px]">cloud_done</span> Autosaved 2m ago</span>
</div>
<div class="flex items-center gap-4">
<span>Ln 24, Col 12</span>
<span>UTF-8</span>
<span class="text-primary font-bold">Pro Account</span>
</div>
</footer>
</main>
</div>
</body></html>