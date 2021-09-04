from prometheus_client import start_http_server, Gauge, Enum, Info
import argparse
import asyncio
import socket
import time
import os
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.harvester_rpc_client import HarvesterRpcClient
from chia.rpc.farmer_rpc_client import FarmerRpcClient
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.cmds.netspace_funcs import netstorge_async as w
from chia.cmds.farm_funcs import get_average_block_time

NETSPACE = Gauge("chia_netspace_total", "Current total netspace")
BLOCK_TIME = Gauge("chia_average_block_time", "Average time between blocks")
HEIGHT = Gauge("chia_block_height", "Current highest block")
SYNC_STATE = Enum("chia_sync_state", "Current sync state", states=["synced", "syncing"])
BALANCE = Gauge("chia_wallet_balance", "Balance of wallets", ["name", "id"])
CONNECTIONS = Gauge("chia_node_connections", "Currently open connections to node", ["type"])
PLOTS_TOTAL = Gauge("chia_plots_count", "Total plots farmed by harvester")
PLOTS_SIZE = Gauge("chia_plots_size", "Total plot size farmed by harvester")
FARMED_AMOUNT = Gauge("chia_farmed_amount", "Total XCH farmed by harvester")
FARMED_LAST = Gauge("chia_farmed_last_block", "Last height a farm reward was farmed")
TIME_TO_WIN = Gauge("chia_time_to_win", "Expected time to win ")
REWARD_ADDRESS = Info("chia_reward_address", "Farming rewards go to this address ")
DIFFICULTY = Gauge("chia_difficulty", "Current blockchain difficulty ")
HARVESTERS_PLOTS = Gauge("chia_plots_count_by_hostname", "Total plots by hostname", ["hostname"])
HARVESTERS_PLOTS_SIZE = Gauge("chia_plots_size_by_hostname", "Total plot size by hostname", ["hostname"])

def parse_args():
    parser = argparse.ArgumentParser(description="This python is a prometheus exporter for the chia blockchain.")
    parser.add_argument("-f", "--fullnode", default="localhost", help="Host machine for the Chia full node RPC server")
    parser.add_argument("-w", "--wallet", default="localhost", help="Host machine for the Chia wallet RPC server")
    parser.add_argument("-a", "--harvester", default="localhost", help="Host machine for the Chia harvester RPC server")
    parser.add_argument("-r", "--farmer", default="localhost", help="Host machine for the Chia farmer RPC server")
    parser.add_argument("-p", "--port", default=9825, type=int, help="Port to listen on for the exporter")

    try:
        args = parser.parse_args()
    except Exception as e:
        parser.print_help()
        raise e

    return args

async def run_metrics(fullnode, wallet, harvester, farmer):
    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        rpc_host = fullnode
        rpc_port = config["full_node"]["rpc_port"]
        wallet_host = wallet
        wallet_rpc_port = config["wallet"]["rpc_port"]
        harvester_host = harvester
        harvester_rpc_port = config["harvester"]["rpc_port"]
        farmer_host = farmer
        farmer_rpc_port = config["farmer"]["rpc_port"]
        client = await WalletRpcClient.create(wallet_host, wallet_rpc_port, DEFAULT_ROOT_PATH, config)
        client_node = await FullNodeRpcClient.create(rpc_host, rpc_port, DEFAULT_ROOT_PATH, config)
        client_harvester = await HarvesterRpcClient.create(harvester_host, harvester_rpc_port, DEFAULT_ROOT_PATH, config)
        client_farmer = await FarmerRpcClient.create(farmer_host, farmer_rpc_port, DEFAULT_ROOT_PATH, config)

        # wallet stuff
        wallets = await client.get_wallets()
        wallet_amounts = {}
        for wallet in wallets:
            balance = await client.get_wallet_balance(wallet["id"])
            # wallet_amounts[wallet['name']] = balance['confirmed_wallet_balance']
            BALANCE.labels(name=wallet["name"], id=wallet["id"]).set(
                balance["confirmed_wallet_balance"]
            )

        # blockchain stuff
        blockchain = await client_node.get_blockchain_state()
        netspace = blockchain["space"]
        NETSPACE.set(netspace)
        difficulty = blockchain["difficulty"]
        DIFFICULTY.set(difficulty)
        average_block_time = await get_average_block_time(rpc_port)
        BLOCK_TIME.set(average_block_time)
        status = blockchain["sync"]["synced"]
        if not status:
            SYNC_STATE.state("syncing")
        else:
            SYNC_STATE.state("synced")
        height = await client.get_height_info()
        HEIGHT.set(height)

        # connections
        connections = await client_node.get_connections()
        sum_connections_by_type = {}
        for connection in connections:
            if connection["type"] not in sum_connections_by_type:
                sum_connections_by_type[connection["type"]] = 0
            sum_connections_by_type[connection["type"]] += 1
        for connection_type, sum_connections in sum_connections_by_type.items():
            CONNECTIONS.labels(type=connection_type).set(sum_connections)

        # harvester stats
        plots = await client_harvester.get_plots()
        plot_count = len(plots["plots"])
        PLOTS_TOTAL.set(plot_count)
        plot_size_total = 0
        for plot in plots["plots"]:
            plot_size_total += plot["file_size"]
        PLOTS_SIZE.set(plot_size_total)
        farmed_stat = await client.get_farmed_amount()
        farmed_amount = farmed_stat["farmed_amount"]
        FARMED_AMOUNT.set(farmed_amount)
        farmed_last_height = farmed_stat["last_height_farmed"]
        FARMED_LAST.set(farmed_last_height)


        # Farmer stuff
        all_harvesters = await client_farmer.get_harvesters()
        total_plots = 0
        total_size = 0
        for harvester in all_harvesters["harvesters"]:
            hostname = socket.gethostbyaddr(harvester["connection"]["host"])[0]
            HARVESTERS_PLOTS.labels(hostname=hostname).set(len(harvester["plots"]))
            harvester_size = 0
            total_plots = total_plots + len(harvester["plots"])
            for plot in harvester["plots"]:
                harvester_size = harvester_size + plot["file_size"]
            HARVESTERS_PLOTS_SIZE.labels(hostname=hostname).set(harvester_size)
            total_size = total_size + harvester_size

        PLOTS_TOTAL.set(total_plots)
        PLOTS_SIZE.set(total_size)
        proportion = total_size / netspace if netspace else -1
        seconds = int(average_block_time) / proportion if proportion else -1
        TIME_TO_WIN.set(seconds)
        reward_address = await client_farmer.get_reward_targets(False)
        REWARD_ADDRESS.info(
            {
                "farmer_target": reward_address["farmer_target"],
                "pool_target": reward_address["pool_target"],
            }
        )

    except Exception as e:
        print("error connecting to something")
        print(e)

    finally:
        if (wallet):
            client.close()
        if (fullnode):
            client_node.close()
        if (harvester):
            client_harvester.close()
        if (farmer):
            client_farmer.close()


if __name__ == "__main__":
    args = parse_args()
    start_http_server(args.port)
    while True:
        asyncio.run(run_metrics(args.fullnode, args.wallet, args.harvester, args.farmer))
        time.sleep(15)
