use std::collections::BTreeMap;

#[derive(Debug, Clone, PartialEq)]
pub struct MoneyAmount {
    pub amount: f64,
    pub currency: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct FxRates {
    pub display_currency: String,
    pub rates: BTreeMap<String, f64>,
}

impl FxRates {
    pub fn convert(&self, money: &MoneyAmount) -> f64 {
        if money.currency == self.display_currency {
            return money.amount;
        }

        match self.rates.get(&money.currency) {
            Some(rate) => money.amount * rate,
            None => money.amount,
        }
    }
}

pub fn sum_money(amounts: &[MoneyAmount], rates: &FxRates) -> f64 {
    amounts.iter().map(|amount| rates.convert(amount)).sum()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sums_native_and_converted_money() {
        let rates = FxRates {
            display_currency: "CZK".to_string(),
            rates: BTreeMap::from([("EUR".to_string(), 25.0), ("USD".to_string(), 23.0)]),
        };
        let amounts = vec![
            MoneyAmount {
                amount: 100.0,
                currency: "CZK".to_string(),
            },
            MoneyAmount {
                amount: 2.0,
                currency: "EUR".to_string(),
            },
        ];

        assert_eq!(sum_money(&amounts, &rates), 150.0);
    }
}

