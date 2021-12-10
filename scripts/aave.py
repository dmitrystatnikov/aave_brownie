from re import A
from brownie import Contract, config, network, interface
from scripts.helpers import get_account
from web3 import Web3

NETWORK_CONFIG = config["networks"][network.show_active()]


class ContractWrap:
    """
    Base class python interface to contracts
    """

    def __init__(self, contract):
        self.contract = contract

    def contract_address(self):
        return self.contract.address


class ContractPayable(ContractWrap):
    """
    Base class python interface to contracts
    """

    def __init__(self, account, contract):
        super().__init__(contract)
        self.account = account

    def account_address(self):
        return self.account.address

    def from_account(self):
        return {"from": self.account}


class AggregatorV3(ContractWrap):
    """
    Python interface to aggregator feeds like USD/ETH price feed
    """

    def __init__(self, contract_address):
        super().__init__(interface.AggregatorV3Interface(contract_address))

    def latestRoundData(self):
        return self.contract.latestRoundData()

    def decimals(self):
        return self.contract.decimals()


class PriceFeed:
    def __init__(self, contract_address, invert_value=False):
        self.contract = AggregatorV3(contract_address)
        self.precision = self.contract.decimals()
        self.process_ratio = (
            PriceFeed._invert_ratio if invert_value else PriceFeed._identity_ratio
        )

    def conversion_rate(self):
        ratio = self.contract.latestRoundData()[1] / (10 ** self.precision)
        return self.process_ratio(ratio)

    def _invert_ratio(ratio):
        return 1.0 / ratio

    def _identity_ratio(ratio):
        return ratio


class ERC20Contract(ContractPayable):
    """
    Python interface for communication with ERC20 contract
    """

    def __init__(self, account, contract_address):
        super().__init__(account, interface.IERC20(contract_address))

    def approve(self, spender, amount):
        return self.contract.approve(spender, amount, self.from_account())


class WETHContract(ContractPayable):
    """
    Python interface for communication with WETH contract
    """

    def __init__(self, account):
        super().__init__(account, interface.IWeth(NETWORK_CONFIG["weth_contract"]))

    def deposit(self, amount):
        return self.contract.deposit({"from": self.account, "value": amount})

    def withdraw(self, amount):
        return self.contract.withdraw(amount, self.from_account())

    def approve(self, spender, amount):
        return self.contract.approve(spender, amount, self.from_account())


class LendingPool(ContractPayable):
    """
    Python interface to AAVE LandingPool contract
    """

    def __init__(self, account):
        super().__init__(account, LendingPool._init_lending_pool())

    def deposit(self, asset, amount):
        return self.contract.deposit(
            asset, amount, self.account_address(), 0, self.from_account()
        )

    def withdraw(self, asset, amount):
        return self.contract.withdraw(
            asset, amount, self.account_address(), self.from_account()
        )

    def borrow(self, asset, amount, interest_mode):
        return self.contract.borrow(
            asset,
            amount,
            interest_mode,
            0,
            self.account_address(),
            self.from_account(),
        )

    def repay(self, asset, amount, interest_mode):
        return self.contract.repay(
            asset, amount, interest_mode, self.account_address(), self.from_account()
        )

    def user_account_data(self):
        return self.contract.getUserAccountData(self.account_address())

    def current_debt_limit(self, price_feed=None):
        available_eth = self.user_account_data()[2]
        if not price_feed:
            return available_eth
        return Web3.fromWei(available_eth * price_feed.conversion_rate(), "ether")

    def _init_lending_pool():
        address_provider = interface.ILendingPoolAddressesProvider(
            NETWORK_CONFIG["aave_lpap"]
        )
        return interface.ILendingPool(address_provider.getLendingPool())


def main():
    # Definitions
    press_key = "Press aney key to continue..."
    account = get_account()
    amount = Web3.toWei(0.1, "ether")
    # Convert to WETH
    weth_converter = WETHContract(account)
    tx = weth_converter.deposit(amount)
    tx.wait(1)
    input(f"Acquired WETH! {press_key}")
    # Approve spending to aave's lending pool
    lending_pool = LendingPool(account)
    tx = weth_converter.approve(lending_pool.contract_address(), amount)
    tx.wait(1)
    input(f"Spending amount approved! {press_key}")
    # Deposit ETH
    tx = lending_pool.deposit(weth_converter.contract_address(), amount)
    tx.wait(1)
    input(f"Amount depositted! {press_key}")
    # Get borrowing limits and borrow DAI
    dai_eth_converter = PriceFeed(NETWORK_CONFIG["dai_eth_price_feed"], True)
    available_dai = lending_pool.current_debt_limit(dai_eth_converter)
    dai_amount = float(
        input(f"Available DAI to borrow: {available_dai}. Enter amount to borrow:")
    )
    input(f"Please confirm amount to borrow: {dai_amount} DAI. {press_key}")
    dai_amount = Web3.toWei(dai_amount, "ether")
    tx = lending_pool.borrow(NETWORK_CONFIG["dai_contract"], dai_amount, 1)
    tx.wait(1)
    dai_amount = Web3.fromWei(dai_amount, "ether")
    health_factor = Web3.fromWei(lending_pool.user_account_data()[5], "ether")
    input(
        f"Amount borrowed: {dai_amount}, your current health factor: {health_factor}. {press_key}"
    )
    # Repay debt
    user_status = lending_pool.user_account_data()
    collateral = Web3.fromWei(user_status[0], "ether")
    debt = Web3.fromWei(user_status[1] * dai_eth_converter.conversion_rate(), "ether")
    credit = Web3.fromWei(user_status[2], "ether")
    health_factor = Web3.fromWei(user_status[5], "ether")
    print(
        f"collateral {collateral} ETH, debt {debt} DAI, available credit {credit} ETH, health factor {health_factor}."
    )
    dai_amount = input("Enter amount to repay:")
    dai_amount = Web3.toWei(dai_amount, "ether")
    if dai_amount > 0:
        dai_contract = ERC20Contract(account, NETWORK_CONFIG["dai_contract"])
        dai_contract.approve(lending_pool.contract_address(), dai_amount).wait(1)
        lending_pool.repay(dai_contract.contract_address(), dai_amount, 1).wait(1)
    user_status = lending_pool.user_account_data()
    collateral = Web3.fromWei(user_status[0], "ether")
    debt = Web3.fromWei(user_status[1], "ether")
    credit = Web3.fromWei(user_status[2], "ether")
    health_factor = Web3.fromWei(user_status[5], "ether")
    print(
        f"Yor final state: collateral {collateral} ETH, debt {debt} DAI, available credit {credit} ETH, health factor {health_factor}."
    )
    # Withdraw funds
    withdrawal_amount = input("Enter amount to withdraw:")
    withdrawal_amount = Web3.toWei(withdrawal_amount, "ether")
    lending_pool.withdraw(weth_converter.contract_address(), withdrawal_amount).wait(1)
    amount_withdrawn = Web3.fromWei(withdrawal_amount, "ether")
    weth_converter.withdraw(withdrawal_amount).wait(1)
    input(f"Amount withdrawn: {amount_withdrawn}. {press_key}")
