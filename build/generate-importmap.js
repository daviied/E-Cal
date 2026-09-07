// Resolves the actual browser ESM entry file for a locally npm-installed
// package so we can vendor it and reference it from a static import map,
// without hardcoding a filename that might change between versions.
const fs = require('fs');
const path = require('path');

// Walks an arbitrarily nested "exports" conditions object (browser/production/
// import/default/etc, in any order/depth) and returns the first string value
// found, preferring keys that look like ESM ("import"/"default" before
// "require"/"node").
function firstStringLeaf(node) {
  if (typeof node === 'string') return node;
  if (!node || typeof node !== 'object') return null;
  const preferredKeys = ['import', 'default', 'browser', 'production', 'module'];
  for (const key of preferredKeys) {
    if (key in node) {
      const found = firstStringLeaf(node[key]);
      if (found) return found;
    }
  }
  for (const key of Object.keys(node)) {
    const found = firstStringLeaf(node[key]);
    if (found) return found;
  }
  return null;
}

function resolveEntry(pkgDir) {
  const pkg = JSON.parse(fs.readFileSync(path.join(pkgDir, 'package.json'), 'utf8'));
  let entry = pkg.module || pkg.main;
  const exp = pkg.exports && (pkg.exports['.'] || pkg.exports);
  const fromExports = firstStringLeaf(exp);
  if (fromExports) entry = fromExports;
  if (!entry || typeof entry !== 'string') throw new Error(`Could not resolve browser entry for ${pkgDir}`);
  return entry;
}

const mathliveEntry = resolveEntry(path.resolve('node_modules/mathlive'));

const map = {
  imports: {
    mathlive: '/lib/mathlive/' + path.basename(mathliveEntry),
  },
};

fs.mkdirSync('out', { recursive: true });
fs.writeFileSync('out/import-map.json', JSON.stringify(map, null, 2));
console.log('Generated import map:', JSON.stringify(map));
