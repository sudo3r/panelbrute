import asyncio
import aiohttp
import argparse
import re
import random
from typing import List, Optional
from colorama import Fore, Style

PORTS = [2082, 2083, 2086, 2087]
completed_domains = 0
total_domains = 0

def log(message, level="i"):
    levels = {
        "i": f"{Fore.LIGHTBLUE_EX}[*]{Style.RESET_ALL}",
        "s": f"{Fore.LIGHTGREEN_EX}[+]{Style.RESET_ALL}",
        "w": f"{Fore.LIGHTYELLOW_EX}[!]{Style.RESET_ALL}",
        "e": f"{Fore.LIGHTRED_EX}[-]{Style.RESET_ALL}",
    }
    print(f"{levels.get(level, levels['i'])} {message}")

async def check_url(session: aiohttp.ClientSession, url: str, timeout: float, proxy: Optional[str] = None) -> bool:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout), ssl=False, proxy=proxy) as response:
            if response.status == 200:
                text = await response.text()
                title_pattern = re.compile(r'<title>[^<]*cPanel[^<]*</title>|<title>[^<]*WHM[^<]*</title>', re.IGNORECASE)
                if title_pattern.search(text):
                    return True
                if 'cpanel' in url.lower() or 'whm' in url.lower():
                    return True
                if 'cPanel, Inc.' in text or 'WebHost Manager' in text:
                    return True
            return False
    except asyncio.TimeoutError:
        log(f"Timeout on {url} (Proxy: {proxy or 'None'})", level="w")
        return False
    except aiohttp.ClientError as e:
        log(f"Error checking {url} (Proxy: {proxy or 'None'}): {e}", level="e")
        return False

async def process_domain(
    session: aiohttp.ClientSession,
    domain: str,
    ports: List[int],
    timeout: float,
    semaphore: asyncio.Semaphore,
    output_file: str,
    proxies: List[str],
    single_proxy: str
) -> None:
    global completed_domains
    async with semaphore:
        for port in ports:
            for protocol in ['https']:
                url = f"{protocol}://{domain}:{port}"
                proxy = single_proxy if single_proxy else random.choice(proxies) if proxies else None
                log(f"Checking {url} (Proxy: {proxy or 'None'})", level="i")
                if await check_url(session, url, timeout, proxy):
                    log(f"Login page found: {url} (Proxy: {proxy or 'None'})", level="s")
                    try:
                        with open(output_file, 'a') as f:
                            f.write(f"{url} (Proxy: {proxy or 'None'})\n")
                    except Exception as e:
                        log(f"Error saving to output file: {e}", level="e")
        completed_domains += 1
        if completed_domains % 1000 == 0:
            progress = (completed_domains / total_domains * 100) if total_domains > 0 else 0
            remaining = total_domains - completed_domains
            log(f"Progress: {completed_domains}/{total_domains} domains scanned ({progress:.1f}% complete, {remaining} remaining)")

async def main(
    input_file: str,
    output_file: str,
    concurrency: int,
    timeout: float,
    proxy_file: str,
    single_proxy: str
) -> None:
    global total_domains, completed_domains
    try:
        with open(input_file, 'r') as f:
            domains = [line.strip() for line in f if line.strip()]
    except Exception as e:
        log(f"Error reading input file: {e}", level="e")
        return

    proxies = []
    if proxy_file:
        try:
            with open(proxy_file, 'r') as f:
                proxies = [line.strip() for line in f if line.strip()]
            log(f"Loaded {len(proxies)} proxies from {proxy_file}", level="i")
        except Exception as e:
            log(f"Error reading proxy file: {e}", level="e")
            return

    total_domains = len(domains)
    completed_domains = 0
    log(f"Total domains: {total_domains}", level="i")

    try:
        open(output_file, 'w').close()
    except Exception as e:
        log(f"Error clearing output file: {e}", level="e")
        return

    connector = aiohttp.TCPConnector(limit=0, ssl=False)
    timeout_settings = aiohttp.ClientTimeout(total=timeout)
    semaphore = asyncio.Semaphore(concurrency)

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout_settings
    ) as session:
        tasks = [
            process_domain(session, domain, PORTS, timeout, semaphore, output_file, proxies, single_proxy)
            for domain in domains
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    log(f"Finished checking. Results saved to {output_file}", level="s")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Check domains for cPanel/WHM login pages')
    parser.add_argument('-i', '--input-file', required=True, help='Input file with list of domains (one per line)')
    parser.add_argument('-o', '--output-file', required=True, help='Output file to store login page URLs')
    parser.add_argument('-c', '--concurrency', type=int, default=50, help='Max concurrent requests (default: 50)')
    parser.add_argument('-t', '--timeout', type=float, default=10.0, help='Timeout per request in seconds (default: 10.0)')
    parser.add_argument('-p', '--proxy', help='Single proxy URL (e.g., http://proxy:port or socks5://proxy:port)')
    parser.add_argument('-pf', '--proxy-file', help='File with list of proxies (one per line)')

    args = parser.parse_args()

    if args.proxy and args.proxy_file:
        log("Cannot use both single proxy and proxy file. Please specify only one.", level="e")
    else:
        asyncio.run(main(
            args.input_file,
            args.output_file,
            args.concurrency,
            args.timeout,
            args.proxy_file,
            args.proxy
        ))