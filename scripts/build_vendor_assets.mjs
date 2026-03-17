import { copyFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, '..');
const vendorDir = resolve(repoRoot, 'webui', 'static', 'vendor');
const fontDir = resolve(vendorDir, 'fonts');

mkdirSync(vendorDir, { recursive: true });
mkdirSync(fontDir, { recursive: true });

const assets = [
  {
    source: resolve(repoRoot, 'node_modules', 'jquery', 'dist', 'jquery.min.js'),
    destination: resolve(vendorDir, 'jquery-3.7.1.min.js'),
  },
  {
    source: resolve(repoRoot, 'node_modules', 'marked', 'lib', 'marked.umd.js'),
    destination: resolve(vendorDir, 'marked-17.0.4.umd.js'),
  },
  {
    source: resolve(repoRoot, 'node_modules', '@fontsource', 'space-grotesk', 'files', 'space-grotesk-latin-400-normal.woff2'),
    destination: resolve(fontDir, 'space-grotesk-400.woff2'),
  },
  {
    source: resolve(repoRoot, 'node_modules', '@fontsource', 'space-grotesk', 'files', 'space-grotesk-latin-500-normal.woff2'),
    destination: resolve(fontDir, 'space-grotesk-500.woff2'),
  },
  {
    source: resolve(repoRoot, 'node_modules', '@fontsource', 'space-grotesk', 'files', 'space-grotesk-latin-700-normal.woff2'),
    destination: resolve(fontDir, 'space-grotesk-700.woff2'),
  },
  {
    source: resolve(repoRoot, 'node_modules', '@fontsource', 'ibm-plex-mono', 'files', 'ibm-plex-mono-latin-400-normal.woff2'),
    destination: resolve(fontDir, 'ibm-plex-mono-400.woff2'),
  },
  {
    source: resolve(repoRoot, 'node_modules', '@fontsource', 'ibm-plex-mono', 'files', 'ibm-plex-mono-latin-500-normal.woff2'),
    destination: resolve(fontDir, 'ibm-plex-mono-500.woff2'),
  },
  {
    source: resolve(repoRoot, 'node_modules', '@fontsource', 'ibm-plex-mono', 'files', 'ibm-plex-mono-latin-600-normal.woff2'),
    destination: resolve(fontDir, 'ibm-plex-mono-600.woff2'),
  },
];

for (const asset of assets) {
  copyFileSync(asset.source, asset.destination);
  console.log(`Copied ${asset.destination}`);
}
