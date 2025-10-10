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



#       ПОВТОРЕНИЕ
#   В Python есть несколько основных типов данных.

#   1. Числа (Numbers)
# Используются для работы с числами: целыми, дробными и комплексными.
# int — целые числа.
# float — числа с плавающей точкой (дробные).
# complex — комплексные числа.

# Примеры:
# int (целое число)
age = 25
print(type(age)) # <class 'int'>
# float (дробное число)
height = 5.9
print(type(height)) # <class 'float'>
# complex (комплексное число)
z = 3 + 4j
print(type(z)) # <class 'complex'>

#   2. Строки (Strings)
# Хранят текст. Строки заключаются в одинарные, двойные или тройные кавычки.
# Примеры:

# Строки
name = "Alice"
greeting = 'Hello!'
multiline_text = """This is
a multiline string."""
print(type(name)) # <class 'str'>
# Можно работать с каждой буквой строки:
# Индексация
print(name[0]) # 'A' (первая буква)
print(name[-1]) # 'e' (последняя буква)

#   3. Логический тип (Boolean)
# Всего два значения: True или False. Используется для проверки условий.
# Пример:
is_active = True
is_admin = False
print(type(is_active)) # <class 'bool'>

#   4. Списки (Lists)
# Хранят набор данных. Элементы списка могут быть разных типов.
# Примеры:

# Список чисел
numbers = [1, 2, 3, 4]
# Список смешанных типов
mixed = [True, "Python", 3.14]
print(type(numbers)) # <class 'list'>
print(numbers[0]) # 1

#   5. Кортежи (Tuples)
# Похожи на списки, но неизменяемы.
# Пример:
colors = ("red", "green", "blue")
print(type(colors)) # <class 'tuple'>
print(colors[0]) # 'red'

#   6. Множества (Sets)
# Хранят уникальные элементы (дубликаты удаляются) и не имеют порядка.
# Пример:
unique_numbers = {1, 2, 3, 3, 4}
print(unique_numbers) # {1, 2, 3, 4}
print(type(unique_numbers)) # <class 'set'>

#   7. Словари (Dictionaries)
# Хранят пары "ключ-значение". Очень удобны для хранения данных с привязкой к ключам.
# Пример:
user = {
"name": "Alice",
"age": 25,
"is_admin": False
}
print(user["name"]) # Alice
print(type(user)) # <class 'dict'>

#   8. None
# Специальный тип, который говорит, что значение отсутствует.
# Пример:
result = None
print(type(result)) # <class 'NoneType'>

#       Каждый из этих типов используется в разных ситуациях. Например:
#       Для чисел — расчёты.
#       Для строк — работа с текстом.
#       Для словарей — структурированные данные.