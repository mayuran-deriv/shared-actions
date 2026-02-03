import { useState } from 'react';
import './Calculator.css';

function Calculator() {
  const [display, setDisplay] = useState('0');
  const [previousValue, setPreviousValue] = useState(null);
  const [operation, setOperation] = useState(null);
  const [waitingForOperand, setWaitingForOperand] = useState(false);

  const handleDigit = (digit) => {
    if (waitingForOperand) {
      setDisplay(String(digit));
      setWaitingForOperand(false);
    } else {
      setDisplay(display === '0' ? String(digit) : display + digit);
    }
  };

  const handleDecimal = () => {
    if (waitingForOperand) {
      setDisplay('0.');
      setWaitingForOperand(false);
    } else if (display.indexOf('.') === -1) {
      setDisplay(display + '.');
    }
  };

  const handleOperation = (nextOperation) => {
    const inputValue = parseFloat(display);

    if (previousValue === null) {
      setPreviousValue(inputValue);
    } else if (operation) {
      const currentValue = previousValue || 0;
      const newValue = calculate(currentValue, inputValue, operation);

      setDisplay(String(newValue));
      setPreviousValue(newValue);
    }

    setWaitingForOperand(true);
    setOperation(nextOperation);
  };

  const calculate = (firstValue, secondValue, operation) => {
    switch (operation) {
      case '+':
        return firstValue + secondValue;
      case '-':
        return firstValue - secondValue;
      case '*':
        return firstValue * secondValue;
      case '/':
        return firstValue / secondValue;
      default:
        return secondValue;
    }
  };

  const handleEquals = () => {
    const inputValue = parseFloat(display);

    if (previousValue !== null && operation) {
      const newValue = calculate(previousValue, inputValue, operation);
      setDisplay(String(newValue));
      setPreviousValue(null);
      setOperation(null);
      setWaitingForOperand(true);
    }
  };

  const handleClear = () => {
    setDisplay('0');
    setPreviousValue(null);
    setOperation(null);
    setWaitingForOperand(false);
  };

  const handleClearEntry = () => {
    setDisplay('0');
  };

  const handleBackspace = () => {
    if (display.length > 1) {
      setDisplay(display.slice(0, -1));
    } else {
      setDisplay('0');
    }
  };

  return (
    <div className="calculator">
      <div className="calculator-display">{display}</div>
      <div className="calculator-buttons">
        <button className="calculator-button function" onClick={handleClear}>
          AC
        </button>
        <button className="calculator-button function" onClick={handleClearEntry}>
          CE
        </button>
        <button className="calculator-button function" onClick={handleBackspace}>
          ←
        </button>
        <button className="calculator-button operator" onClick={() => handleOperation('/')}>
          ÷
        </button>

        <button className="calculator-button" onClick={() => handleDigit(7)}>
          7
        </button>
        <button className="calculator-button" onClick={() => handleDigit(8)}>
          8
        </button>
        <button className="calculator-button" onClick={() => handleDigit(9)}>
          9
        </button>
        <button className="calculator-button operator" onClick={() => handleOperation('*')}>
          ×
        </button>

        <button className="calculator-button" onClick={() => handleDigit(4)}>
          4
        </button>
        <button className="calculator-button" onClick={() => handleDigit(5)}>
          5
        </button>
        <button className="calculator-button" onClick={() => handleDigit(6)}>
          6
        </button>
        <button className="calculator-button operator" onClick={() => handleOperation('-')}>
          −
        </button>

        <button className="calculator-button" onClick={() => handleDigit(1)}>
          1
        </button>
        <button className="calculator-button" onClick={() => handleDigit(2)}>
          2
        </button>
        <button className="calculator-button" onClick={() => handleDigit(3)}>
          3
        </button>
        <button className="calculator-button operator" onClick={() => handleOperation('+')}>
          +
        </button>

        <button className="calculator-button zero" onClick={() => handleDigit(0)}>
          0
        </button>
        <button className="calculator-button" onClick={handleDecimal}>
          .
        </button>
        <button className="calculator-button operator equals" onClick={handleEquals}>
          =
        </button>
      </div>
    </div>
  );
}

export default Calculator;
