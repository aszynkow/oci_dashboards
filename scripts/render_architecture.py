#!/usr/bin/env python3
"""Render the one-page repository architecture; no OCI access or deployment.

Uses committed original OCI catalog vector artwork; see icon provenance.json.
Requires rsvg-convert (librsvg). The SVG is a standalone editable artifact.
"""
from copy import deepcopy
from html import escape
from pathlib import Path
import shutil
import subprocess
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/design'
ICONS = OUT / 'oci-icons'
BARK, RED, OCEAN = '#312D2A', '#C74634', '#2C5967'
NEUTRAL, AIR, BORDER = '#F5F4F2', '#FCFBFA', '#DFDCD8'
parts = []


def add(value):
    parts.append(value)


def rect(x, y, w, h, fill=AIR, stroke=BORDER, radius=10, dash=False):
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"'+(' stroke-dasharray="7 5"' if dash else '')+'/>')


def text(x, y, content, size=18, weight='400', color=BARK, anchor='start'):
    add(f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">{escape(content)}</text>')


def icon(name, x, y, size=58):
    root = deepcopy(ET.parse(ICONS / (name + '.svg')).getroot())
    root.set('x', str(x)); root.set('y', str(y))
    root.set('width', str(size)); root.set('height', str(size))
    add(ET.tostring(root, encoding='unicode'))


def arrow(path, dashed=False):
    add(f'<path d="{path}" fill="none" stroke="{BARK}" stroke-width="2" marker-end="url(#arrow)"'+(' stroke-dasharray="6 5"' if dashed else '')+'/>')


def service(x, y, w, title, detail, glyph, height=142):
    rect(x, y, w, height, 'white')
    icon(glyph, x + w/2 - 27, y + 13, 54)
    text(x+w/2, y+90, title, 20, '600', anchor='middle')
    for i, line in enumerate(detail):
        text(x+w/2, y+(108 if len(detail)>1 else 115)+i*18, line, 15, anchor='middle')


def analytics(x, y, title, detail, height=142):
    rect(x, y, 300, height, 'white')
    icon('log-analytics', x+19, y+19, 56)
    text(x+88, y+40, 'Log Analytics', 22, '600')
    text(x+88, y+67, title, 17, '500', OCEAN)
    for i, line in enumerate(detail):text(x+20, y+101+i*21, line, 16)


def dashboard(x, y, title, lines, height=142):
    rect(x, y, 460, height, '#F2F7F8', '#AABFC6')
    # Generic Console window notation, not an invented OCI service icon.
    rect(x+20, y+20, 44, 35, 'white', OCEAN, 3)
    add(f'<path d="M{x+20} {y+29}h44 M{x+32} {y+29}v26" fill="none" stroke="{OCEAN}"/>')
    text(x+80, y+41, title, 25, '600')
    text(x+80, y+66, 'Native OCI Console dashboard + saved searches', 16, color=OCEAN)
    for i, line in enumerate(lines):text(x+22, y+102+i*22, line, 17)


def auxiliary(x, y, w, glyph, title, subtitle):
    rect(x, y, w, 70, 'white')
    icon(glyph, x+12, y+11, 46)
    text(x+72, y+29, title, 20, '600')
    text(x+72, y+51, subtitle, 15)


def main():
    parts.clear()
    add('<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">')
    add('<title>OCI Block Volume Backup Dashboards — deployed architecture</title>')
    add('<desc>Native backup completion events flow through Events, Streaming and Connector Hub to Log Analytics and an Activity dashboard. An hourly read-only Function inventories the same source compartments and publishes coverage snapshots and metrics. Terraform and Python manage deployment; OCI Logging stores Function diagnostics.</desc>')
    add('<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M1 1L8 4.5L1 8" fill="none" stroke="#312D2A" stroke-width="1.4"/></marker></defs>')
    add('<g font-family="Arial, Helvetica, sans-serif">')
    rect(0, 0, 1920, 1080, AIR, 'none', 0)
    rect(0, 0, 1920, 9, RED, 'none', 0)
    text(40, 66, 'OCI Block Volume Backup Dashboards', 43, '600')
    text(40, 108, 'Event activity + optional inventory coverage • OCI Console native dashboards', 23, color='#70736E')
    text(1880, 65, 'DEPLOYED ARCHITECTURE', 18, '600', OCEAN, 'end')
    rect(40, 135, 1840, 675, NEUTRAL, '#9E9892', 12)
    text(65, 172, 'ORACLE CLOUD INFRASTRUCTURE  /  DEPLOYMENT PROFILE REGION', 19, '600')
    text(1840, 172, 'Existing network • exact configured compartment scope', 17, color='#70736E', anchor='end')
    text(390, 228, '01  ACTIVITY  /  NATIVE BACKUP & COPY COMPLETION EVENTS', 19, '600', OCEAN)
    text(390, 458, '02  COVERAGE  /  HOURLY READ-ONLY INVENTORY', 19, '600', OCEAN)
    # Connectors are drawn before cards and kept out of text areas.
    for start, end in [(355,390),(550,585),(765,800),(1000,1040),(1340,1380)]:arrow(f'M{start} 331H{end-5}')
    arrow('M590 577H640')
    arrow('M955 577H1035')
    arrow('M1340 577H1375')
    arrow('M685 650V675H360')
    text(490, 666, 'Read-only Block Storage APIs', 15, anchor='middle')
    arrow('M830 710V655')
    text(845, 699, 'Image pull', 14)
    add(f'<path d="M955 615H1008V689H1440" fill="none" stroke="{BARK}" stroke-width="2"/>')
    arrow('M1160 689V710')
    arrow('M1440 689V710')
    add('<circle cx="1160" cy="689" r="3" fill="#312D2A"/>')
    text(1160, 678, 'Runtime telemetry', 15, anchor='middle')
    # Existing source resources are shared by both observation paths.
    rect(70, 245, 285, 520, 'white', '#9E9892', 8, True)
    text(212, 274, 'SOURCE COMPARTMENTS', 17, '600', anchor='middle')
    icon('block-storage', 171, 297, 82)
    text(212, 410, 'Block volumes + groups', 22, '600', anchor='middle')
    for y, line in [(446,'Backups + member backups'),(477,'Backup policy assignments')]:text(212,y,line,18,anchor='middle')
    add('<path d="M95 514H330" stroke="#DFDCD8"/>')
    text(212, 551, 'Existing resources', 18, '600', anchor='middle')
    text(212, 582, 'No backup or policy writes', 17, anchor='middle')
    text(212, 613, 'Boot volumes excluded', 17, anchor='middle')
    text(212, 710, 'Same allowlist for both flows', 16, '600', OCEAN, 'middle')
    text(212, 738, 'Root UI filters do not expand scans', 15, anchor='middle')
    service(390,260,160,'Events',['Completion rules'],'events')
    service(585,260,180,'Streaming',['New or existing stream'],'streaming')
    service(800,260,200,'Connector Hub',['Stream → Log Analytics'],'connector-hub')
    analytics(1040,260,'Activity source / group',['Custom JSON parser & fields','Deduplicate by native event ID'])
    dashboard(1380,260,'Activity dashboard',['Direct + group backup / copy outcomes','24h / 7d counts • 30d trends & failure history'])
    rect(620,480,375,180,'none',OCEAN,8,True)
    text(638,502,'EXISTING VCN / FUNCTION SUBNET',15,'600',OCEAN)
    service(390,515,200,'Resource Scheduler',['Hourly, minute :10 UTC'],'generic-service',135)
    service(645,515,310,'OCI Function',['Resource principal • read-only inventory','Recovery targets + grace + freshness'],'functions',135)
    analytics(1040,515,'Coverage source / group',['Structured per-volume snapshots','Separate parser & custom fields'],135)
    dashboard(1380,515,'Coverage dashboard',['Covered / approaching / not covered / unknown','Counts & percentages • deadlines • collection health'],135)
    auxiliary(645,715,350,'container-registry','Container Registry (OCIR)','Private repository • pinned image digest')
    auxiliary(1040,715,245,'monitoring','Monitoring','backup_coverage')
    auxiliary(1315,715,285,'logging','Logging','Invoke logs • 30 days')
    # Home-region identity resources are outside the regional runtime grouping.
    rect(40,824,1840,51,'#EDF1EB',BORDER,8)
    icon('iam',57,831,37)
    text(110,846,'TENANCY HOME REGION  /  IAM POLICIES + FUNCTION & SCHEDULE DYNAMIC GROUPS',17,'600')
    text(110,867,'Least privilege: scoped inventory reads, telemetry writes and scheduled invocation. Events and Connector Hub use scoped service-principal policies.',16)
    rect(40,890,1840,131,'white',BORDER,10)
    text(65,918,'LOCAL DEPLOYMENT  /  PYTHON + TERRAFORM',17,'600',OCEAN)
    steps=[(70,'1  Profile + tfvars → JSON','Tenancy / region from OCI profile'),
           (490,'2  OCIR state → build + push','Docker / Colima • source-versioned image'),
           (955,'3  Plan → Python schema setup','Custom fields, JSON parser and sources'),
           (1425,'4  Apply infrastructure state','Dashboard JSON imported with Terraform')]
    for x, title, subtitle in steps:
        text(x,960,title,22,'600');text(x,990,subtitle,17)
    for start,end in [(432,470),(900,935),(1370,1405)]:arrow(f'M{start} 963H{end}')
    text(40,1051,'Activity counts completion events. Coverage counts distinct observed volumes. Neither proves restore success or required DR-copy availability.',17)
    text(40,1075,'Solid arrows: runtime data / service access.  Missing or stale data is unknown.  Coverage is optional; no VM is required.',14,color='#70736E')
    text(1880,1075,'Artwork: OCI Architecture Diagram Toolkit v23.1 • Oracle',13,color='#70736E',anchor='end')
    add('</g></svg>')
    target=OUT/'backup-dashboard-architecture.svg'
    target.write_text('\n'.join(line.rstrip() for line in '\n'.join(parts).splitlines())+'\n')
    renderer=shutil.which('rsvg-convert')
    if not renderer:raise SystemExit('Install librsvg / rsvg-convert to render the PNG')
    png=target.with_suffix('.png')
    subprocess.run([renderer,'-w','2880','-h','1620','-o',str(png),str(target)],check=True)
    # Retain the established documentation path for existing links/bookmarks.
    shutil.copyfile(png,OUT/'backup-activity-design.png')
    print(target.relative_to(ROOT));print(png.relative_to(ROOT));print('Updated docs/design/backup-activity-design.png')


if __name__ == '__main__':
    main()
