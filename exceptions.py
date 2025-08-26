#   Обработка ошибок, исключений (exceptions) - позволяет продолжить выполнение программы без экстренного завершения,
#   например, выводить окно с ошибкой, вместо завершении работы: ValueError: invalid literal for int() with base 10: '10bc'
#   в идеале все исключения должны быть обработаны

try:  # 1 часть блока для обработки - внутри пишем любые конструкции
    a = '10bc'
    print(int(a))  # ValueError: invalid literal for int() with base 10: '10bc'
except ValueError as e:  # 2 часть блока для обработки: указываем какую ошибку будем ловить, as - короткое наименование
    print('Получена ошибка ValueError: ', e.args)
    #   Получена ошибка ValueError:  ("invalid literal for int() with base 10: '10bc'",)

# Вариант, когда нужно обработать несколько исключений:
try:
    a = '10bc'
    c = 10 / 0  # ZeroDivisionError: division by zero
    print(int(a))  # ValueError: invalid literal for int() with base 10: '10bc'
except (ValueError, ZeroDivisionError) as e:
    print('Получена ошибка: ', e.args)
    #   Получена ошибка:  ('division by zero',)

# Вариант, когда не знаем какое исключение можем поймать:
try:
    a = '10bc'
    c = 10 / 0  # ZeroDivisionError: division by zero
    print(int(a))  # ValueError: invalid literal for int() with base 10: '10bc'
except Exception as e:  # Такое не сильно приветствуется, лучше понимать какие исключения можем поймать, но тоже вариант!
    print('Получена ошибка: ', e.args)
    #   Получена ошибка:  ('division by zero',)

# Вариант, когда нужно обработать отдельно каждую конкретную ошибку:
try:
    a = '10bc'
    c = 10 / 0  # ZeroDivisionError: division by zero
    print(int(a))  # ValueError: invalid literal for int() with base 10: '10bc'
except ValueError as e:
    print('Получена ошибка ValueError: ', e.args)
except ZeroDivisionError as e:
    print('Получена ошибка ZeroDivisionError: ', e.args)
    #   Получена ошибка ZeroDivisionError:  ('division by zero',)

# Вариант с finally, который выполнится всегда:
try:
    a = '10bc'
    c = 10 / 0  # ZeroDivisionError: division by zero
    print(int(a))  # ValueError: invalid literal for int() with base 10: '10bc'
except ValueError as e:
    print('Получена ошибка ValueError: ', e.args)
except ZeroDivisionError as e:
    print('Получена ошибка ZeroDivisionError: ', e.args)
finally:  # 3 часть блока для обработки - он выполняется в любом случае, независимо от результата в 1-м блоке try
    print('Я блок, который выполняется всегда')
    #   Я блок, который выполняется всегда

# Вариант с else, который выполнится, если не будет выполняться Exception:
try:
    a = '10bc'
    # c = 10 / 0  # ZeroDivisionError: division by zero
    # print(int(a))  # ValueError: invalid literal for int() with base 10: '10bc'
except ValueError as e:
    print('Получена ошибка ValueError: ', e.args)
except ZeroDivisionError as e:
    print('Получена ошибка ZeroDivisionError: ', e.args)
else:
    print('Исключения не появились, код работает отлично')
finally:  # 3 часть блока для обработки - он выполняется в любом случае, независимо от результата в 1-м блоке try
    print('Я блок, который выполняется всегда')
    #   Я блок, который выполняется всегда

# Популярные типы исключений:
#   ValueError - Неправильное значение передано функции (Например, попытка преобразовать строку в число).
#   TypeError - Попытка выполнить операцию между объектами несовместимых типов.
#   ZeroDivisionError - Деление на ноль.
#   IndexError - Попытка обратиться к несуществующему элементу списка.
#   KeyError - Попытка обратиться к несуществующему ключу в словаре.
#   FileNotFoundError - Попытка открыть файл, которого нет.
#   ImportError / ModuleNotFoundError - Ошибка при попытке импортировать несуществующий модуль.
#   AttributeError - Попытка обратиться к несуществующему атрибуту объекта.
#   NameError - Обращение к переменной, которая не была определена.
#   IndentationError - Ошибка отступов в коде.
#   SyntaxError - Синтаксическая ошибка в коде.
#   MemoryError - Недостаточно памяти для выполнения операции.
#   RuntimeError - Общая ошибка, которая возникает в процессе выполнения программы.

# Еще примеры с популярными исключениями:
#   1. ValueError
try:
    number = int("abc")  # Невозможно преобразовать строку "abc" в число
except ValueError:
    print("Неправильное значение!")

#   2. TypeError
try:
    result = "5" + 5  # Нельзя сложить строку и число
except TypeError:
    print("Нельзя складывать строку и число!")

#   3. IndexError
my_list = [1, 2, 3]
try:
    print(my_list[5])  # Элемента с индексом 5 нет
except IndexError:
    print("Выход за границы списка!")
#   4. KeyError
my_dict = {"name": "Alice"}
try:
    print(my_dict["age"])
except KeyError:
    print("Такого ключа нет в словаре!")  # Ключ "age" не существует

#   5. FileNotFoundError
try:
    with open("nonexistent_file.txt", "r") as file:
        content = file.read()
except FileNotFoundError:
    print("Файл не найден!")

# Как создать свою ошибку?
# Можно создать и "выбросить" свою ошибку с помощью команды raise
# raise используется для вызова исключения (выбрасывания ошибки).
# Это оператор, который позволяет вручную остановить выполнение программы и сообщить, что что-то пошло не так:
age = -5
if age < 0:
    raise ValueError("Возраст не может быть отрицательным!")  # ValueError: Возраст не может быть отрицательным!

### Пример из жизни. Программа для ввода числа с защитой от ошибок:
while True:
    try:
        number = int(input("Введите число: "))
        print(f"Вы ввели число: {number}")
        break  # Выход из цикла, если ошибок нет
    except ValueError:
        print("Это не число! Попробуйте снова.")
