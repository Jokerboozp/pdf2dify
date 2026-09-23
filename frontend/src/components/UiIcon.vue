<script setup lang="ts">
defineProps<{ name: string; size?: number }>()

const paths: Record<string, string> = {
  add: 'M12 5v14M5 12h14',
  arrow: 'M5 12h14m-6-6 6 6-6 6',
  check: 'M20 6 9 17l-5-5',
  chevron: 'm9 18 6-6-6-6',
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 5v5l3 2',
  close: 'M18 6 6 18M6 6l12 12',
  database: 'M12 3c-5 0-8 1.6-8 3.5S7 10 12 10s8-1.6 8-3.5S17 3 12 3ZM4 6.5v5C4 13.4 7 15 12 15s8-1.6 8-3.5v-5M4 11.5v5C4 18.4 7 20 12 20s8-1.6 8-3.5v-5',
  download: 'M12 3v12m-4-4 4 4 4-4M4 17v3h16v-3',
  edit: 'm16 4 4 4M4 20l4.5-1 11-11a2.8 2.8 0 0 0-4-4l-11 11L4 20Z',
  eye: 'M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6Zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z',
  file: 'M6 3h8l4 4v14H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Zm8 0v5h5M8 13h8M8 17h6',
  folder: 'M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10H3V7Z',
  grid: 'M3 3h8v8H3zM13 3h8v8h-8zM3 13h8v8H3zM13 13h8v8h-8z',
  link: 'M10 13a5 5 0 0 0 7.1 0l2-2A5 5 0 0 0 12 3.9l-1.2 1.2M14 11a5 5 0 0 0-7.1 0l-2 2A5 5 0 0 0 12 20.1l1.2-1.2',
  pause: 'M8 5v14M16 5v14',
  play: 'm8 5 11 7-11 7V5Z',
  refresh: 'M20 7v5h-5M4 17v-5h5M5.8 9A7 7 0 0 1 18 7l2 5M4 12l2 5a7 7 0 0 0 12.2-2',
  search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm6-2 4 4',
  settings: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm8 4a8 8 0 0 0-.2-1.8l1.4-1.1-1.8-3.1-1.7.7a8 8 0 0 0-3.1-1.8L14.3 3h-3.6l-.3 1.9a8 8 0 0 0-3.1 1.8l-1.7-.7-1.8 3.1 1.4 1.1a8 8 0 0 0 0 3.6l-1.4 1.1 1.8 3.1 1.7-.7a8 8 0 0 0 3.1 1.8l.3 1.9h3.6l.3-1.9a8 8 0 0 0 3.1-1.8l1.7.7 1.8-3.1-1.4-1.1A8 8 0 0 0 20 12Z',
  trash: 'M4 7h16M9 7V4h6v3m3 0-1 14H7L6 7M10 11v6M14 11v6',
  upload: 'M12 16V4m-4 4 4-4 4 4M4 16v4h16v-4',
}
</script>

<template>
  <svg :width="size || 18" :height="size || 18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path :d="paths[name] || paths.file" />
  </svg>
</template>
