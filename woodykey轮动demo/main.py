from telegram import FetchPalmmicroData

def calculate_annualized_return(principal, total_return, years):
    # 计算年化收益率公式：final_amount = principal * (1 + rate)^years
    # 解方程：rate = (final_amount / principal)^(1/years) - 1
    rate = ((principal + total_return) / principal) ** (1 / years) - 1
    return rate * 100  # 转换为百分比

def main():
    import sys
    print(f"Hello, World! {sys.version}")
    result = calculate_annualized_return(350, 168, 10)
    print(f"总结：无敌哥10年赚168万，本金350万，年化收益率为：{result:.2f}%")
    FetchPalmmicroData("SZ160719,SZ161125,SZ162411")

main()
