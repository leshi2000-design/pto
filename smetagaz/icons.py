from PyQt6.QtGui import QIcon,QPixmap,QPainter
from PyQt6.QtCore import QByteArray,Qt
from PyQt6.QtSvg import QSvgRenderer
PATHS={
'workspace':'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
'clients':'M9 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M2 21v-2a7 7 0 0 1 14 0v2 M17 4a4 4 0 0 1 0 8 M19 15a5 5 0 0 1 3 5',
'tasks':'M9 5h12 M9 12h12 M9 19h12 M2 5l2 2 3-4 M2 12l2 2 3-4 M2 19l2 2 3-4',
'estimates':'M5 2h10l4 4v16H5z M14 2v5h5 M8 11h8 M8 15h8 M8 19h5',
'contracts':'M5 2h10l4 4v16H5z M8 10h8 M8 14h5 M8 18l2-2 2 3 3-4',
'gsv':'M3 6h11v5h7v7H10v-5H3z M6 3v13 M18 9v12',
'gsn':'M3 11l9-8 9 8 M5 10v11h14V10 M9 21v-7h6v7',
'gsn_catalog':'M4 4h16v16H4z M8 8h8 M8 12h8 M8 16h5',
'smr':'M3 21h18 M5 21V9l7-5 7 5v12 M9 21v-6h6v6 M9 12h6',
'legal_entities':'M4 21V4h9v17 M13 9h7v12h-7 M7 8h1 M7 12h1 M7 16h1 M16 13h1 M16 17h1',
'exec':'M3 5h7l2 3h9v13H3z M7 14l3 3 6-6',
'materials':'M3 7l9-5 9 5v10l-9 5-9-5z M3 7l9 5 9-5 M12 12v10',
'welders':'M14 2L4 14h7l-1 8 10-13h-7z',
'gsv_catalog':'M3 4h7v16H3z M14 4h7v16h-7z M6 8h1 M17 8h1',
'calculators':'M5 2h14v20H5z M8 5h8v4H8z M8 13h1 M15 13h1 M8 17h1 M15 17h1',
'writeoff':'M4 4h16v17H4z M8 8h8 M8 12h8 M8 16h4',
'stats':'M3 3v18h18 M7 17v-5 M12 17V8 M17 17V4',
'settings':'M3 6h18 M3 12h18 M3 18h18 M8 3v6 M16 9v6 M8 15v6'}
def icon(name,color='#bdcce1'):
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><path d="{PATHS.get(name,PATHS["workspace"])}" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    pix=QPixmap(48,48);pix.fill(Qt.GlobalColor.transparent);p=QPainter(pix);QSvgRenderer(QByteArray(svg.encode())).render(p);p.end();return QIcon(pix)
