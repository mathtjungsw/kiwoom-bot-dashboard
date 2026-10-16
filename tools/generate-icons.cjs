// Generates a static sprite from the installed Lucide library, not hand-drawn icons.
const fs = require('node:fs');
const path = require('node:path');
const modules = path.resolve(process.argv[2] || 'node_modules');
const React = require(path.join(modules,'react'));
const {renderToStaticMarkup} = require(path.join(modules,'react-dom/server'));
const lucide = require(path.join(modules,'lucide-react'));
const names=['ChartNoAxesCombined','Clock3','TrendingUp','CircleHelp','ShieldCheck','Database','History','ChevronDown','ChevronLeft','ChevronRight','LockKeyhole','Eye','RefreshCw','LogOut','Activity','CircleAlert','Pause','X'];
const id=name=>name.replace(/([a-z0-9])([A-Z])/g,'$1-$2').replace(/([a-z])([0-9])/g,'$1-$2').toLowerCase();
const symbols=names.map(name=>`<symbol id="${id(name)}" viewBox="0 0 24 24">${renderToStaticMarkup(React.createElement(lucide[name],{size:24}))}</symbol>`);
fs.writeFileSync(path.join(__dirname,'../docs/icons.svg'),`<svg xmlns="http://www.w3.org/2000/svg">${symbols.join('')}</svg>\n`);
fs.writeFileSync(path.join(__dirname,'../docs/icon.svg'),renderToStaticMarkup(React.createElement(lucide.ChartNoAxesCombined,{size:32,color:'#2457d6'}))+'\n');
