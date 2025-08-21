# This is a sample Python script.
from xmlrpc.client import boolean


# Press ⌃R to execute it or replace it with your code.
# Press Double ⇧ to search everywhere for classes, files, tool windows, actions, and settings.


def print_hi(name):
    # Use a breakpoint in the code line below to debug your script.
    print(f'Hi, {name}')  # Press ⌘F8 to toggle the breakpoint.


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    # print_hi('Misha')

    # Типы данных(integer, float, boolean, string, list, dictionary)
    number = 100  # integer - целые числа
    another_number = "100"  # string
    float_number = 10.5  # float - числа с плавающей запятой (но используется только точка)
    text = "Цитата: \"программировать легко\""  # string. тут используется экранирование, но можно и без него
    another_text = 'текст: "цитата"'  # string. просто используя разные ковычки
    boolean_value = True  # boolean. True - это 1, если складывать с др типами данных
    another_boolean_value = False  # boolean. False - это 0, если складывать с др типами данных
    a, b, c = 20, 10, 56  # вот так перечисленные значения тоже выводятся

    values = [10, "число", 4,
              9]  # list - список элементов, обычно в квадратных скобках, нумерация значений начинается с нуля!
    list_dictionary = {0: 10, 1: "число", 2: 4, 3: 9}
    dictionary = {"car": "машина", "dog": "собака",
                  "cat": "кошка"}  # dictionary - словарь, в нем перечисляются пары "ключ": "значение"

    print(a)

    # print(number, another_number, sep=" % ") # sep - это разделитель
# print(dictionary["cat"]) тут название словаря[номер] - если список; название словаря["ключ"] - если словарь

# Кортеж(tuple) в Python — это список, который нельзя изменить.
