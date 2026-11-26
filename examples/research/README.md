# 调研示例：Python 项目怎样运行测试

## 当前结论

对于使用标准库 `unittest` 的项目，可以从项目根目录运行 `python -m unittest discover -s tests`。先确认项目规定的框架和入口，沿用它的配置。

## 证据与范围

- [Python 官方文档：命令行接口](https://docs.python.org/3/library/unittest.html#command-line-interface) 说明了按模块、类和方法运行测试。
- [Python 官方文档：测试发现](https://docs.python.org/3/library/unittest.html#test-discovery) 说明了发现模式和起始目录。上面的命令假定项目测试位于 `tests/`。
- 本例查的是标准库 `unittest` 的用法，项目接入取决于实际测试目录和环境。

## 续查示例

下一次只问“怎么跑一个测试方法”时，先读上面的命令行文档。对可导入的测试模块，可用 `python -m unittest tests.test_sample.SampleTests.test_case`。追加这条结论和适用条件到当前文档，供下一位接手者继续使用。
