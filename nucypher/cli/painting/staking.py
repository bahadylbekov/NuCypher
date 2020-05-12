"""
This file is part of nucypher.

nucypher is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

nucypher is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with nucypher.  If not, see <https://www.gnu.org/licenses/>.
"""


import tabulate
from typing import List
from web3.main import Web3

from nucypher.blockchain.eth.constants import NULL_ADDRESS, STAKING_ESCROW_CONTRACT_NAME
from nucypher.blockchain.eth.token import NU
from nucypher.blockchain.eth.utils import prettify_eth_amount, datetime_at_period
from nucypher.cli.painting.transactions import paint_receipt_summary


def paint_stakes(emitter, stakeholder, paint_inactive: bool = False, staker_address: str = None):
    headers = ('Idx', 'Value', 'Remaining', 'Enactment', 'Termination')
    staker_headers = ('Status', 'Restaking', 'Winding Down', 'Unclaimed Fees', 'Min reward rate')

    stakers = stakeholder.get_stakers()
    if not stakers:
        emitter.echo("No staking accounts found.")

    total_stakers = 0
    for staker in stakers:
        if not staker.stakes:
            # This staker has no active stakes.
            # TODO: Something with non-staking accounts?
            continue

        # Filter Target
        if staker_address and staker.checksum_address != staker_address:
            continue

        stakes = sorted(staker.stakes, key=lambda s: s.address_index_ordering_key)
        active_stakes = filter(lambda s: s.is_active, stakes)
        if not active_stakes:
            emitter.echo(f"There are no active stakes\n")

        fees = staker.policy_agent.get_reward_amount(staker.checksum_address)
        pretty_fees = prettify_eth_amount(fees)
        last_confirmed = staker.staking_agent.get_last_active_period(staker.checksum_address)
        missing = staker.missing_confirmations
        min_reward_rate = prettify_eth_amount(staker.min_reward_rate)

        if missing == -1:
            missing_info = "Never Confirmed (New Stake)"
        else:
            missing_info = f'Missing {missing} confirmation{"s" if missing > 1 else ""}' if missing else f'Confirmed #{last_confirmed}'

        staker_data = [missing_info,
                       f'{"Yes" if staker.is_restaking else "No"} ({"Locked" if staker.restaking_lock_enabled else "Unlocked"})',
                       "Yes" if bool(staker.is_winding_down) else "No",
                       pretty_fees,
                       min_reward_rate]

        line_width = 54
        if staker.registry.source:  # TODO: #1580 - Registry source might be Falsy in tests.
            network_snippet = f"\nNetwork {staker.registry.source.network.capitalize()} "
            snippet_with_line = network_snippet + '═'*(line_width-len(network_snippet)+1)
            emitter.echo(snippet_with_line, bold=True)
        emitter.echo(f"Staker {staker.checksum_address} ════", bold=True, color='red' if missing else 'green')
        emitter.echo(f"Worker {staker.worker_address} ════")
        emitter.echo(tabulate.tabulate(zip(staker_headers, staker_data), floatfmt="fancy_grid"))

        rows = list()
        for index, stake in enumerate(stakes):
            if not stake.is_active and not paint_inactive:
                # This stake is inactive.
                continue
            rows.append(list(stake.describe().values()))
        total_stakers += 1
        emitter.echo(tabulate.tabulate(rows, headers=headers, tablefmt="fancy_grid"))  # newline

    if not total_stakers:
        emitter.echo("No Stakes found", color='red')


def prettify_stake(stake, index: int = None) -> str:
    start_datetime = stake.start_datetime.local_datetime().strftime("%b %d %H:%M %Z")
    expiration_datetime = stake.unlock_datetime.local_datetime().strftime("%b %d %H:%M %Z")
    duration = stake.duration

    pretty_periods = f'{duration} periods {"." if len(str(duration)) == 2 else ""}'

    pretty = f'| {index if index is not None else "-"} ' \
             f'| {stake.staker_address[:6]} ' \
             f'| {stake.worker_address[:6]} ' \
             f'| {stake.index} ' \
             f'| {str(stake.value)} ' \
             f'| {pretty_periods} ' \
             f'| {start_datetime} - {expiration_datetime} ' \

    return pretty


def paint_staged_stake_division(emitter,
                                stakeholder,
                                original_stake,
                                target_value,
                                extension):
    new_end_period = original_stake.final_locked_period + extension
    new_duration_periods = new_end_period - original_stake.first_locked_period + 1
    staking_address = original_stake.staker_address

    division_message = f"""
Staking address: {staking_address}
~ Original Stake: {prettify_stake(stake=original_stake, index=None)}
"""

    paint_staged_stake(emitter=emitter,
                       stakeholder=stakeholder,
                       staking_address=staking_address,
                       stake_value=target_value,
                       lock_periods=new_duration_periods,
                       start_period=original_stake.first_locked_period,
                       unlock_period=new_end_period + 1,
                       division_message=division_message)


def paint_staged_stake(emitter,
                       stakeholder,
                       staking_address,
                       stake_value,
                       lock_periods,
                       start_period,
                       unlock_period,
                       division_message: str = None):
    start_datetime = datetime_at_period(period=start_period,
                                        seconds_per_period=stakeholder.economics.seconds_per_period,
                                        start_of_period=True)

    unlock_datetime = datetime_at_period(period=unlock_period,
                                         seconds_per_period=stakeholder.economics.seconds_per_period,
                                         start_of_period=True)

    start_datetime_pretty = start_datetime.local_datetime().strftime("%b %d %H:%M %Z")
    unlock_datetime_pretty = unlock_datetime.local_datetime().strftime("%b %d %H:%M %Z")

    if division_message:
        emitter.echo(f"\n{'═' * 30} ORIGINAL STAKE {'═' * 28}", bold=True)
        emitter.echo(division_message)

    emitter.echo(f"\n{'═' * 30} STAGED STAKE {'═' * 30}", bold=True)

    emitter.echo(f"""
Staking address: {staking_address}
~ Chain      -> ID # {stakeholder.wallet.blockchain.client.chain_id} | {stakeholder.wallet.blockchain.client.chain_name}
~ Value      -> {stake_value} ({int(stake_value)} NuNits)
~ Duration   -> {lock_periods} Days ({lock_periods} Periods)
~ Enactment  -> {start_datetime_pretty} (period #{start_period})
~ Expiration -> {unlock_datetime_pretty} (period #{unlock_period})
    """)

    # TODO: periods != Days - Do we inform the user here?

    emitter.echo('═'*73, bold=True)


def paint_stakers(emitter, stakers: List[str], staking_agent, policy_agent) -> None:
    current_period = staking_agent.get_current_period()
    emitter.echo(f"\nCurrent period: {current_period}")
    emitter.echo("\n| Stakers |\n")
    emitter.echo(f"{'Checksum address':42}  Staker information")
    emitter.echo('=' * (42 + 2 + 53))

    for staker in stakers:
        nickname, pairs = nickname_from_seed(staker)
        symbols = f"{pairs[0][1]}  {pairs[1][1]}"
        emitter.echo(f"{staker}  {'Nickname:':10} {nickname} {symbols}")
        tab = " " * len(staker)

        owned_tokens = staking_agent.owned_tokens(staker)
        last_confirmed_period = staking_agent.get_last_active_period(staker)
        worker = staking_agent.get_worker_from_staker(staker)
        is_restaking = staking_agent.is_restaking(staker)
        is_winding_down = staking_agent.is_winding_down(staker)

        missing_confirmations = current_period - last_confirmed_period
        owned_in_nu = round(NU.from_nunits(owned_tokens), 2)
        locked_tokens = round(NU.from_nunits(staking_agent.get_locked_tokens(staker)), 2)

        emitter.echo(f"{tab}  {'Owned:':10} {owned_in_nu}  (Staked: {locked_tokens})")
        if is_restaking:
            if staking_agent.is_restaking_locked(staker):
                unlock_period = staking_agent.get_restake_unlock_period(staker)
                emitter.echo(f"{tab}  {'Re-staking:':10} Yes  (Locked until period: {unlock_period})")
            else:
                emitter.echo(f"{tab}  {'Re-staking:':10} Yes  (Unlocked)")
        else:
            emitter.echo(f"{tab}  {'Re-staking:':10} No")
        emitter.echo(f"{tab}  {'Winding down:':10} {'Yes' if is_winding_down else 'No'}")
        emitter.echo(f"{tab}  {'Activity:':10} ", nl=False)
        if missing_confirmations == -1:
            emitter.echo(f"Next period confirmed (#{last_confirmed_period})", color='green')
        elif missing_confirmations == 0:
            emitter.echo(f"Current period confirmed (#{last_confirmed_period}). "
                         f"Pending confirmation of next period.", color='yellow')
        elif missing_confirmations == current_period:
            emitter.echo(f"Never confirmed activity", color='red')
        else:
            emitter.echo(f"Missing {missing_confirmations} confirmations "
                         f"(last time for period #{last_confirmed_period})", color='red')

        emitter.echo(f"{tab}  {'Worker:':10} ", nl=False)
        if worker == NULL_ADDRESS:
            emitter.echo(f"Worker not set", color='red')
        else:
            emitter.echo(f"{worker}")

        fees = prettify_eth_amount(policy_agent.get_reward_amount(staker))
        emitter.echo(f"{tab}  Unclaimed fees: {fees}")

        min_rate = prettify_eth_amount(policy_agent.get_min_reward_rate(staker))
        emitter.echo(f"{tab}  Min reward rate: {min_rate}")


def paint_staking_confirmation(emitter, staker, new_stake):
    emitter.echo("\nStake initialization transaction was successful.", color='green')
    emitter.echo(f'\nTransaction details:')
    paint_receipt_summary(emitter=emitter, receipt=new_stake.receipt, transaction_type="deposit stake")
    emitter.echo(f'\n{STAKING_ESCROW_CONTRACT_NAME} address: {staker.staking_agent.contract_address}', color='blue')
    next_steps = f'''\nView your stakes by running 'nucypher stake list'
or set your Ursula worker node address by running 'nucypher stake set-worker'.

See https://docs.nucypher.com/en/latest/guides/staking_guide.html'''
    emitter.echo(next_steps, color='green')


def paint_staking_accounts(emitter, wallet, registry):
    from nucypher.blockchain.eth.actors import Staker

    rows = list()
    for account in wallet.accounts:
        eth = str(Web3.fromWei(wallet.eth_balance(account), 'ether')) + " ETH"
        nu = str(NU.from_nunits(wallet.token_balance(account, registry)))

        staker = Staker(is_me=True, checksum_address=account, registry=registry)
        staker.stakes.refresh()
        is_staking = 'Yes' if bool(staker.stakes) else 'No'
        rows.append((is_staking, account, eth, nu))
    headers = ('Staking', 'Account', 'ETH', 'NU')
    emitter.echo(tabulate.tabulate(rows, showindex=True, headers=headers, tablefmt="fancy_grid"))